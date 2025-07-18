import ast
import re
import logging
from typing import List, Any
from llama_index.core.llms import ChatResponse
import networkx as nx
import community as community_louvain
from sqlglot import parse_one, exp, transpile
import sqlglot
import sqlglot.expressions as exp
from typing import Tuple, Optional, Union
from transformers import AutoTokenizer
from functools import lru_cache
from response.log_manager import log_prompt


# Configure logging
logger = logging.getLogger(__name__)

    
def extract_table_list(response: ChatResponse) -> list:
    """Extracts a list of table names from a response string that may contain code blocks."""
    # First, strip any code block formatting
    cleaned_response = response.message.content

    think_pattern = r'<think>[\s\S]*?</think>'
    think_match = re.search(think_pattern, cleaned_response)
    
    if think_match:
        # Only process text after the </think> tag
        cleaned_response = cleaned_response[think_match.end():].strip()
    
    # Remove markdown code block if present
    code_block_pattern = r"```(?:python)?\s*([\s\S]*?)\s*```"
    code_block_match = re.search(code_block_pattern, cleaned_response)
    
    if code_block_match:
        # Use the content inside the code block
        cleaned_response = code_block_match.group(1).strip()
    
    try:
        # Try to parse as a Python literal
        return ast.literal_eval(cleaned_response)
    except (SyntaxError, ValueError):
        # Fallback: look for strings in single quotes
        pattern = r"'([^']+)'"
        matches = re.findall(pattern, cleaned_response)
        if matches:
            return matches
            
        # Try double quotes if no single quotes found
        pattern = r'"([^"]+)"'
        matches = re.findall(pattern, cleaned_response)
        if matches:
            return matches
            
        # If no quotes found, split by commas and clean up
        items = [item.strip().strip("'\"") for item in cleaned_response.split(',')]
        return [item for item in items if item]
    



def extract_tables_from_sql(sql_query: str, dialect: str) -> list[str]:
    """
    Extract all table names from a SQL query, excluding tables defined in CTEs.
    
    Args:
        sql_query (str): The SQL query to analyze
        
    Returns:
        List[str]: List of table names referenced in the query (excluding CTE tables)
    """
    # Parse the SQL
    parsed = sqlglot.parse_one(sql_query, read=dialect)
    
    # Get all CTE names
    cte_names = set()
    for cte in parsed.find_all(exp.CTE):
        cte_names.add(cte.alias)
    
    # Extract all table references
    tables = set()
    for table in parsed.find_all(exp.Table):
        table_name = table.name
        # Only add if it's not a CTE
        if table_name not in cte_names:
            tables.add(table_name)
    
    return list(tables)


def schema_clustering(table_details: list, resolution_value = 1.0) -> list:
    """
    Create table relationship arrays with full table details in each cluster.
    
    Args:
        table_details: Danh sách thông tin chi tiết của các bảng
        resolution_value: Tham số resolution cho thuật toán Louvain (mặc định: 1.0)
        
    Returns:
        Danh sách các cụm, mỗi cụm chứa thông tin đầy đủ của các bảng
    """
    try:
        import networkx as nx
        import community as community_louvain
        
        if not table_details:
            return []
        
        # If there are fewer than 5 tables, return one cluster with all tables
        if len(table_details) < 5:
            # Sort tables alphabetically by tableIdentifier
            sorted_tables = sorted(table_details, key=lambda x: x['tableIdentifier'])
            return [sorted_tables]
        
        # Tạo từ điển để lưu thông tin đầy đủ của bảng, với key là tableIdentifier
        table_info_map = {table['tableIdentifier']: table for table in table_details}
        
        # Lấy danh sách các tên bảng
        tables = list(table_info_map.keys())

        # Trích xuất các khóa ngoại
        foreign_keys = []
        for table_info in table_details:
            source_table = table_info['tableIdentifier']
            for column_info in table_info.get('columns', []):
                if column_info.get('relations'): 
                    for relation in column_info['relations']:
                        target_table = relation.get('tableIdentifier')
                        if target_table and source_table in tables and target_table in tables and source_table != target_table:
                            foreign_keys.append((source_table, target_table))
        
        # Loại bỏ các cặp trùng lặp
        foreign_keys = list(set(foreign_keys))

        # Xây dựng đồ thị
        G = nx.Graph()
        G.add_nodes_from(tables)
        G.add_edges_from(foreign_keys)

        if G.number_of_nodes() == 0:
            return []

        # Áp dụng thuật toán Louvain để phân cụm
        if G.number_of_edges() > 0:
            partition = community_louvain.best_partition(G, resolution=resolution_value)
        else:
            partition = {node: i for i, node in enumerate(G.nodes())}
            
        # Xử lý kết quả phân cụm
        communities = {}
        for node, community_id in partition.items():
            if community_id not in communities:
                communities[community_id] = []
            communities[community_id].append(node)

        # Sắp xếp các cụm theo kích thước
        sorted_community_ids = sorted(communities.keys(), 
                                      key=lambda k: len(communities[k]), 
                                      reverse=True)
        
        # Tạo danh sách các cụm với thông tin đầy đủ của bảng
        full_info_clusters = []
        
        for community_id in sorted_community_ids:
            # Lấy danh sách tên bảng trong cụm
            table_ids = communities[community_id]
            # Sắp xếp theo alphabet
            sorted_table_ids = sorted(table_ids)
            
            # Lấy thông tin đầy đủ cho mỗi bảng
            cluster_with_full_info = [table_info_map[table_id] for table_id in sorted_table_ids]
            full_info_clusters.append(cluster_with_full_info)
            
        return full_info_clusters

    except Exception as e:
        print(f"Error in schema_clustering: {e}")
        return []



def schema_parser(tables: list, type: str, include_sample_data: bool = False):
    """
    Phân tích cấu trúc schema và tạo ra các câu lệnh mô tả theo định dạng được chỉ định.
    
    Args:
        tables: Danh sách các bảng cùng thông tin cột và quan hệ
        type: Loại định dạng đầu ra ("DDL", "Synthesis", hoặc "Simple")
        include_sample_data: Có hiển thị dữ liệu mẫu hay không (mặc định: False)
        
    Returns:
        Chuỗi mô tả schema theo định dạng đã chọn
    """
    if type not in ["DDL", "Synthesis", "Simple"]:
        raise Exception("Invalid schema parser type. Must be 'DDL', 'Synthesis', or 'Simple'.")

    if type == "DDL":
        ddl_statements = []
        fk_relationships = []
        
        # First create all tables
        for table in tables:
            table_name = table["tableIdentifier"]
            columns = table["columns"]

            # Create table definition
            column_definitions = []
            
            for column in columns:
                column_def = f"{column['columnIdentifier']} {column['columnType']}"
                if column.get("isPrimaryKey"):
                    column_def += " PRIMARY KEY"
                description = column.get("columnDescription", None)
                if description:
                    if column == columns[-1]:
                        column_def += f" -- {description}"
                    else:
                        column_def += f", -- {description}"
                
                column_definitions.append(column_def)
                
                # Collect foreign key relationships separately
                if "relations" in column and column["relations"]:
                    for relation in column["relations"]:
                        if relation.get("type") == "OTM":  # One-to-Many relationship
                            fk_relation = f"-- {table_name}.{column['columnIdentifier']} can be joined with  {relation['tableIdentifier']}.{relation['toColumn']}"
                            fk_relationships.append(fk_relation)

            # Remove trailing comma from the last column definition
            if column_definitions:
                column_definitions[-1] = column_definitions[-1].rstrip(',')
            
            # Combine into CREATE TABLE statement
            ddl = f"CREATE TABLE {table_name} (\n    " + \
                  "\n    ".join(column_definitions) + "\n);"
            ddl_statements.append(ddl)
            
            # Add sample data if available and requested
            if include_sample_data and "sample_data" in table and table["sample_data"]:
                ddl_statements.append("-- Sample Data:")
                # Add column headers
                column_headers = ", ".join([column["columnIdentifier"] for column in columns])
                ddl_statements.append(f"--\t{column_headers}")
                # Add data rows
                for data_row in table["sample_data"]:
                    ddl_statements.append(f"--\t{data_row}")
                ddl_statements.append("")  # Empty line for better readability

        # Add all foreign key relationships at the end
        if fk_relationships:
            ddl_statements.append("-- Foreign Key Relationships:")
            ddl_statements.append("\n".join(fk_relationships))

        return "\n".join(ddl_statements)

    elif type == "Synthesis":
        synthesis_statements = []
        fk_relationships = []
        
        for table in tables:
            table_name = table["tableIdentifier"]
            columns = table["columns"]

            # Generate synthesis description
            column_descriptions = []
            for column in columns:
                description = column.get("columnDescription", None)
                pk_info = " (Primary Key)" if column.get("isPrimaryKey") else ""
                
                # Collect foreign key relationships separately
                if "relations" in column and column["relations"]:
                    for relation in column["relations"]:
                        fk_relation = f"{table_name}.{column['columnIdentifier']} can be joined with {relation['tableIdentifier']}.{relation['toColumn']}"
                        fk_relationships.append(fk_relation)
                
                if description:
                    column_descriptions.append(
                        f"- {column['columnIdentifier']} ({column['columnType']}){pk_info}: {description}")
                else:
                    column_descriptions.append(
                        f"- {column['columnIdentifier']} ({column['columnType']}){pk_info}")

            synthesis = f"\nTable: {table_name}\n" + "\n".join(column_descriptions)
            synthesis_statements.append(synthesis)
            
            # Add sample data if available and requested
            if include_sample_data and "sample_data" in table and table["sample_data"]:
                synthesis_statements.append("- Sample Data:")
                # Add column headers
                column_headers = ", ".join([column["columnIdentifier"] for column in columns])
                synthesis_statements.append(f"\t{column_headers}")
                # Add data rows
                for data_row in table["sample_data"]:
                    synthesis_statements.append(f"\t{data_row}")
                synthesis_statements.append("")  # Empty line for better readability

        # Add all foreign key relationships at the end
        if fk_relationships:
            synthesis_statements.append("# Foreign Key Relationships:")
            synthesis_statements.append("\n".join([f"- {relation}" for relation in fk_relationships]))

        return "\n".join(synthesis_statements)
    
    elif type == "Simple":
        simple_statements = []
        fk_relationships = []
        
        for table in tables:
            table_name = table["tableIdentifier"]
            columns = table["columns"]

            columns_chain = []
            for column in columns:
                column_name = column["columnIdentifier"]
                column_type = column["columnType"]
                pk_info = " [PK]" if column.get("isPrimaryKey") else ""
                
                columns_chain.append(f"{column_name} {column_type}{pk_info}")
                
                # Collect foreign key relationships separately
                if "relations" in column and column["relations"]:
                    for relation in column["relations"]:
                        fk_relation = f"{table_name}.{column['columnIdentifier']} →  {relation['tableIdentifier']}.{relation['toColumn']}"
                        fk_relationships.append(fk_relation)
            
            simple_statements.append(f"{table_name} ({', '.join(columns_chain)})")
            
            # Add sample data if available and requested
            if include_sample_data and "sample_data" in table and table["sample_data"]:
                simple_statements.append("Sample Data:")
                # Add column headers
                column_headers = ", ".join([column["columnIdentifier"] for column in columns])
                simple_statements.append(f"  {column_headers}")
                # Add data rows
                for data_row in table["sample_data"]:
                    simple_statements.append(f"  {data_row}")
                simple_statements.append("")  # Empty line for better readability

        # Add all foreign key relationships at the end
        if fk_relationships:
            simple_statements.append("\n\nForeign Key Relationships:")
            simple_statements.append("\n".join(fk_relationships))

        return "\n".join(simple_statements)

def log_prompt(prompt_messages: str, step_name: str) -> None:
    """
    Logs the formatted prompt messages with detailed formatting.
    
    Args:
        prompt_messages (list): A list of ChatMessage objects containing the prompt
        step_name (str): The name of the current workflow step
    """
    logger.info(f"\033[95m===== {step_name} PROMPT =====\033[0m")
    logger.info(f"\033[97m{prompt_messages}\033[0m")
    logger.info("\033[95m---------------------\033[0m")
    logger.info(f"\033[95m===== END {step_name} PROMPT =====\033[0m")

def show_prompt(prompt_messages: List[Any]) -> None:
    """
    Displays the formatted prompt messages in a readable format.
    This is a more console-friendly version that uses print instead of logging.

    Args:
        prompt_messages (list): A list of ChatMessage objects containing the prompt.
    """
    print("\nFormatted Prompt Messages:")
    print("-" * 80)
    for message in prompt_messages:
        print(f"Role: {message.role}")
        for block in message.blocks:
            if block.block_type == "text":
                print(f"Content:\n{block.text}")
        print("-" * 80)  # Separator for readability

def extract_sql_query(response_text):
        """
        Extract SQL query from LLM response and return as a single line.
        
        Args:
            response_text: The LLM response text that may contain a SQL query
            
        Returns:
            A single line SQL query without any additional elements
        """
        think_pattern = r'<think>[\s\S]*?</think>'
        think_match = re.search(think_pattern, response_text)
        
        if think_match:
            # Only process text after the </think> tag
            response_text = response_text[think_match.end():].strip()
        
        # Try to extract code blocks with sql, SQL, or no language specified
        sql_pattern = r"```(?:sql|SQL)?\s*([\s\S]*?)```"
        sql_matches = re.findall(sql_pattern, response_text)
        
        if sql_matches:
            # Take the first match if multiple code blocks
            sql = sql_matches[0].strip()
        else:
            # Check for complete SQL query ending with semicolon followed by non-SQL text
            semicolon_split_pattern = r"(SELECT[\s\S]+?;)\s*\w+"
            semicolon_split_match = re.search(semicolon_split_pattern, response_text, re.IGNORECASE)
            
            if semicolon_split_match:
                # Extract the SQL part ending with semicolon
                sql = semicolon_split_match.group(1).strip()
            else:
                # If no code blocks with ``` are found, try to extract the full query differently
                
                # First attempt: look for complete queries with nested subqueries and proper formatting
                # This complex pattern captures SQL with nested parentheses, conditions, etc.
                complex_sql_pattern = r"SELECT[\s\S]+?FROM[\s\S]+?(?:WHERE[\s\S]+?)?(?:GROUP BY[\s\S]+?)?(?:HAVING[\s\S]+?)?(?:ORDER BY[\s\S]+?)?(?:LIMIT\s+\d+)?(?:OFFSET\s+\d+)?(?:;|$)"
                complex_matches = re.findall(complex_sql_pattern, response_text, re.IGNORECASE)
                
                if complex_matches:
                    sql = complex_matches[0].strip()
                else:
                    # Second attempt: try to find a complete SQL statement with semicolon
                    semicolon_pattern = r"SELECT[\s\S]+?;|INSERT[\s\S]+?;|UPDATE[\s\S]+?;|DELETE[\s\S]+?;|CREATE[\s\S]+?;|DROP[\s\S]+?;|ALTER[\s\S]+?;"
                    semicolon_matches = re.findall(semicolon_pattern, response_text, re.DOTALL | re.IGNORECASE)
                    
                    if semicolon_matches:
                        # Take the first complete SQL statement with semicolon
                        sql = semicolon_matches[0].strip()
                    else:
                        # Try a simple approach - collect all lines between SELECT and the end of the query
                        lines = response_text.split('\n')
                        sql_lines = []
                        in_sql = False
                        
                        for line in lines:
                            # Start collecting when we see SELECT
                            if re.search(r'\bSELECT\b', line, re.IGNORECASE) and not in_sql:
                                in_sql = True
                                sql_lines.append(line)
                            # Continue collecting if we're in SQL mode
                            elif in_sql:
                                # Stop if we hit an empty line after collecting some SQL or see end markers
                                if (not line.strip() and len(sql_lines) > 3) or re.search(r'\bEXPLAIN\b|\bANALYZE\b', line, re.IGNORECASE):
                                    break
                                sql_lines.append(line)
                        
                        if sql_lines:
                            sql = '\n'.join(sql_lines)
                        else:
                            # If all else fails, fall back to keyword search
                            sql_keywords = r"(?:SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|WITH|DESCRIBE)"
                            potential_sql_lines = re.findall(fr"(?m)^.*{sql_keywords}.*$", response_text)
                            
                            if potential_sql_lines:
                                # Join potential SQL lines
                                sql = " ".join(line.strip() for line in potential_sql_lines)
                            else:
                                # If nothing looks like SQL, return a default query
                                print("No valid SQL query found in the response, returning default query.")
                                return "SELECT 0;"
        
        # Fix incomplete queries by checking for missing parts
        # 1. Is the query missing column parts?
        if "SELECT" in sql.upper() and "FROM" in sql.upper():
            # Extract SELECT part
            select_match = re.search(r'SELECT\s+(.*?)(?:\s+FROM)', sql, re.IGNORECASE | re.DOTALL)
            
            if select_match:
                select_columns = select_match.group(1).strip()
                
                # If SELECT part seems truncated (e.g., missing commas between selections)
                if ',' in select_columns and select_columns.count(',') < response_text.count(',') and select_columns.endswith(','):
                    # Try to find all selected columns from the original text
                    select_pattern = r'SELECT\s+(.*?)\s+FROM'
                    select_full_match = re.search(select_pattern, response_text, re.IGNORECASE | re.DOTALL)
                    
                    if select_full_match and len(select_full_match.group(1)) > len(select_columns):
                        # Replace only the SELECT part with the better match
                        sql = sql.replace(select_columns, select_full_match.group(1).strip())
        
        # Handle missing parts of the query by parsing the structure and ensuring completeness
        sql_upper = sql.upper()
        
        # Check if we're missing FROM in a SELECT query
        if "SELECT" in sql_upper and "FROM" not in sql_upper:
            from_pattern = r'FROM\s+\w+(?:\s+AS\s+\w+)?'
            from_match = re.search(from_pattern, response_text, re.IGNORECASE)
            
            if from_match:
                sql += " " + from_match.group(0)
        
        # Check if we're missing WHERE in a query that should have it
        if "WHERE" not in sql_upper and "WHERE" in response_text.upper():
            # Find the WHERE clause including any complex conditions and nested queries
            where_pattern = r'WHERE\s+[\s\S]+?(?:GROUP BY|ORDER BY|LIMIT|HAVING|;|$)'
            where_match = re.search(where_pattern, response_text, re.IGNORECASE)
            
            if where_match:
                where_clause = where_match.group(0)
                # Remove anything after the actual WHERE clause
                for ending in ["GROUP BY", "ORDER BY", "LIMIT", "HAVING", ";"]:
                    if ending in where_clause.upper():
                        where_clause = where_clause[:where_clause.upper().find(ending)]
                        break
                
                sql += " " + where_clause.strip()
        
        # Handle subqueries by ensuring complete parentheses balance
        # Count opening and closing parentheses
        open_parens = sql.count('(')
        close_parens = sql.count(')')
        
        # If unbalanced, check original text for the complete subquery
        if open_parens > close_parens:
            # Find the point where we're missing closing parentheses
            for i in range(close_parens, open_parens):
                subquery_pattern = r'\([^()]*(?:\([^()]*\)[^()]*)*\)'  # Match balanced parentheses
                
                # Search for subqueries in the original text that might be missing
                subquery_candidates = re.findall(subquery_pattern, response_text)
                for candidate in subquery_candidates:
                    if candidate not in sql:
                        # We found a subquery that's missing from our extracted SQL
                        # Try to find where it fits
                        opening_pos = -1
                        for j, char in enumerate(sql):
                            if char == '(':
                                opening_pos = j
                                # Check if this is already balanced
                                if sql[j:].count('(') <= sql[j:].count(')'):
                                    continue
                                # Check if this opening might be part of our missing subquery
                                subquery_starts = candidate.find('(')
                                if subquery_starts == 0 and sql[j:j+10] in candidate[:10]:
                                    # This position looks like where our missing subquery fits
                                    sql = sql[:j] + candidate + sql[j+1:]
                                    break
        
        # Ensure all lines of a multi-line SQL statement are included
        if "SELECT" in sql.upper() and sql.strip().startswith("SELECT"):
            # Check if we're potentially missing parts of the query by comparing with original text
            sql_keywords = ["SELECT", "FROM", "WHERE", "GROUP BY", "HAVING", "ORDER BY", "LIMIT"]
            present_keywords = [kw for kw in sql_keywords if kw in sql.upper()]
            
            # Find all occurrences of these keywords in the original text
            for i, keyword in enumerate(present_keywords):
                # Check if there should be something between this keyword and the next one
                if i < len(present_keywords) - 1:
                    current_pos = sql.upper().find(keyword)
                    next_pos = sql.upper().find(present_keywords[i+1])
                    
                    if current_pos >= 0 and next_pos >= 0:
                        # Extract what's between these keywords in our current SQL
                        current_content = sql[current_pos + len(keyword):next_pos].strip()
                        
                        # Find the same section in original text
                        orig_current_pos = response_text.upper().find(keyword)
                        orig_next_pos = response_text.upper().find(present_keywords[i+1])
                        
                        if orig_current_pos >= 0 and orig_next_pos >= 0:
                            orig_content = response_text[orig_current_pos + len(keyword):orig_next_pos].strip()
                            
                            # If original has more content, use it instead
                            if len(orig_content) > len(current_content) and not orig_content.startswith(current_content):
                                # Replace the section with the more complete version
                                sql = sql[:current_pos + len(keyword)] + " " + orig_content + " " + sql[next_pos:]
        
        # Clean up the final SQL statement
        sql = re.sub(r'\s+', ' ', sql).strip()
        
        # Try to grab any columns that might still be missing (check for S.Song_release_year pattern)
        if "SELECT" in sql.upper() and "FROM" in sql.upper():
            match = re.search(r'SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
            if match:
                select_part = match.group(1)
                # Check if the SELECT part appears truncated
                if "," in select_part and select_part.count(",") < response_text.count(","):
                    # Look for column patterns that might be missing
                    column_pattern = r'(?:[A-Za-z]\w*\.)?[A-Za-z]\w*(?:\s+AS\s+\w+)?'
                    original_columns = re.findall(column_pattern, response_text)
                    for col in original_columns:
                        # Check if it looks like a column reference but isn't in our SELECT
                        if '.' in col and col not in select_part:
                            # If it's not in a different part of the query (WHERE, etc.)
                            if col not in sql[sql.upper().find("FROM"):]:
                                select_part += f", {col}"
                    
                    # Update the SQL with the more complete SELECT part
                    sql = sql.replace(match.group(1), select_part)
        
        # Check for a complete SQL query ending with semicolon followed by explanation text
        if ";" in sql:
            sql = sql.split(";")[0] + ";"
        
        # If the result is empty or obviously not SQL, return the default
        if not sql or not any(keyword in sql.upper() for keyword in ["SELECT"]):
            print("Extracted content doesn't appear to be a valid SQL query, returning default query.")
            return "SELECT 0;"
            
        return sql

def is_valid_sql_query(sql_query: str, dialect: str = "postgres") -> Tuple[bool, Optional[Exception]]:

    DIALECTS = [
        "Athena",
        "BigQuery",
        "ClickHouse",
        "Databricks",
        "Doris",
        "Drill",
        "Druid",
        "DuckDB",
        "Dune",
        "Hive",
        "Materialize",
        "MySQL",
        "Oracle",
        "Postgres",
        "Presto",
        "PRQL",
        "Redshift",
        "RisingWave",
        "Snowflake",
        "Spark",
        "Spark2",
        "SQLite",
        "StarRocks",
        "Tableau",
        "Teradata",
        "Trino",
        "TSQL",
    ]
    dialect = dialect.lower()
    if dialect not in [d.lower() for d in DIALECTS]:
        raise ValueError(f"Invalid dialect: {dialect}. Must be one of: {', '.join([d.lower() for d in DIALECTS])}")
    try:
        # 1) Transpile will parse & re-generate; it raises on any syntax error
        transpiled_stmts = sqlglot.transpile(sql_query, read=dialect)
    except Exception as e:
        return False, e

    # 2) Must be exactly one statement
    if len(transpiled_stmts) != 1:
        return False, ValueError("Only a single statement is allowed.")

    try:
        # 3) Parse that one statement into an AST
        root = sqlglot.parse_one(sql_query, read=dialect)
    except Exception as e:
        # This is unlikely if transpile passed, but just in case
        return False, e
    allowed_roots = (exp.Select, exp.Union, exp.Intersect, exp.Except)
    # 4) Enforce a SELECT root
    if not isinstance(root, allowed_roots):
        return False, ValueError("Only SELECT queries are allowed (no DDL or INSERT/UPDATE/DELETE).")

    return True, None

def parse_llm_json_response(response: str) -> dict:
    """
    Phân tích phản hồi có định dạng JSON từ LLM và chuyển đổi thành đối tượng Python.
    
    Args:
        response: Chuỗi phản hồi từ LLM có thể chứa JSON
        
    Returns:
        Dict hoặc List chứa dữ liệu JSON đã được phân tích, hoặc None nếu có lỗi
    """
    import re
    import json
    
    try:
        # Trường hợp 1: Phản hồi đã là JSON hợp lệ
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass
        
        # Trường hợp 2: Tìm kiếm khối code JSON
        json_block_patterns = [
            r'```json\s*([\s\S]*?)\s*```',  # Markdown JSON code block
            r'```\s*([\s\S]*?)\s*```',       # Markdown code block không chỉ định ngôn ngữ
            r'`([\s\S]*?)`'                  # Markdown inline code
        ]
        
        for pattern in json_block_patterns:
            matches = re.search(pattern, response)
            if matches:
                json_content = matches.group(1).strip()
                try:
                    return json.loads(json_content)
                except json.JSONDecodeError:
                    continue
        
        # Trường hợp 3: Tìm chuỗi JSON trong văn bản
        # Tìm dấu ngoặc nhọn/vuông đầu tiên và cuối cùng
        first_brace = min(response.find('{'), response.find('[')) if response.find('{') != -1 and response.find('[') != -1 else max(response.find('{'), response.find('['))
        last_brace = max(response.rfind('}'), response.rfind(']'))
        
        if first_brace != -1 and last_brace != -1:
            json_content = response[first_brace:last_brace+1]
            try:
                return json.loads(json_content)
            except json.JSONDecodeError:
                pass
        
        # Nếu không thể phân tích được, trả về None
        print("Không thể phân tích JSON từ phản hồi của LLM")
        return None
        
    except Exception as e:
        print(f"Lỗi khi phân tích JSON: {str(e)}")
        return None


def parse_schema_enrichment(response: ChatResponse) -> list:
    """
    Phân tích phản hồi JSON từ LLM theo định dạng được chỉ định trong SCHEMA_ENRICHMENT_PROMPT.
    
    Args:
        response: Chuỗi phản hồi từ LLM
        
    Returns:
        List chứa thông tin bảng và cột đã được làm phong phú, hoặc list rỗng nếu có lỗi
    """
    try:
        # Phân tích JSON từ phản hồi
        response = response.message.content
        enriched_data = parse_llm_json_response(response)
        
        if not enriched_data or not isinstance(enriched_data, list):
            return []
        
        # Kiểm tra cấu trúc của dữ liệu đã làm phong phú
        validated_data = []
        for table_info in enriched_data:
            if not isinstance(table_info, dict):
                continue
                
            table_name = table_info.get('table_name')
            description = table_info.get('description')
            columns = table_info.get('columns', [])
            
            if not table_name:
                continue
                
            validated_columns = []
            for column in columns:
                if not isinstance(column, dict):
                    continue
                    
                column_name = column.get('column_name')
                column_description = column.get('description', '')
                
                if column_name:
                    validated_columns.append({
                        'column_name': column_name,
                        'description': column_description
                    })
            
            validated_data.append({
                'table_name': table_name,
                'description': description or '',
                'columns': validated_columns
            })
        
        return validated_data
    except Exception as e:
        print(f"Lỗi khi phân tích phản hồi làm phong phú schema: {str(e)}")
        return []
    

def enrich_schema_with_info(table_details: list, connection_payload: dict):
    """
    Enrich schema with additional information from schema_enrich_info.
    
    Args:
        table_details (list): List of table details from database schema
        connection_payload (dict): Connection payload containing schema enrichment info
        
    Returns:
        tuple: (enriched_table_details, database_description)
    """
    database_description = ""
    
    # First check if schema enrichment is enabled and schema_enrich_info exists
    schema_enrich_info = connection_payload.get("schema_enrich_info")
    should_enrich = (
        schema_enrich_info is not None and 
        isinstance(schema_enrich_info, dict) and
        schema_enrich_info != {}
    )
    
    if should_enrich:
        logger.info(f"Enrich schema is enabled: {should_enrich}")

        # Next, check if enriched_schema exists
        if "enrich_schema" in schema_enrich_info and schema_enrich_info["enrich_schema"] is not None:
            logger.info(f"Retrieved schema with {len(table_details)} tables and enrichment information")
            
            # Create mapping from tableIdentifier to enriched table for faster lookup
            enriched_tables_map = {
                table["tableIdentifier"]: table 
                for table in schema_enrich_info["enrich_schema"]
            }
            
            # Add database description to response data if available
            if "database_description" in schema_enrich_info:
                database_description = schema_enrich_info['database_description']
                logger.info(f"Database description: {database_description}")
            
            for table in table_details:
                table_id = table["tableIdentifier"]
                
                # Check if table exists in mapping
                if table_id in enriched_tables_map:
                    enriched_table = enriched_tables_map[table_id]
                    
                    # Update table description
                    table["tableDescription"] = enriched_table.get("tableDescription", "")
                    logger.info(f"Table [{table_id}] description: {table['tableDescription']}")
                    
                    # Create mapping from columnIdentifier to enriched column
                    enriched_columns_map = {
                        col["columnIdentifier"]: col 
                        for col in enriched_table["columns"]
                    }
                    
                    # Update column descriptions
                    for column in table["columns"]:
                        column_id = column["columnIdentifier"]
                        
                        # Check update conditions and if column exists in mapping
                        is_empty_description = (
                            column.get("columnDescription") in ["", "NULL", "''"] or
                            column.get("columnDescription") is None or
                            len(str(column.get("columnDescription", ""))) <= 1
                        )
                        
                        if is_empty_description and column_id in enriched_columns_map:
                            enriched_column = enriched_columns_map[column_id]
                            column["columnDescription"] = enriched_column.get("columnDescription", "")
                            logger.info(f"\t- Column [{column_id}] description: {column['columnDescription']}")
        else:
            logger.info("Schema enrichment is enabled but 'enrich_schema' is not present or is None")
    else:
        logger.info("Schema enrichment is disabled or no enrichment info available")
    
    return table_details, database_description




@lru_cache
def _load_tokenizer(model_id: str):
    """
    Load and cache the correct tokenizer for each model.
    Qwen needs trust_remote_code=True, Phi-4 thì không.
    """
    kwargs = {"trust_remote_code": True} if model_id.startswith("Qwen/") else {}
    return AutoTokenizer.from_pretrained(model_id, **kwargs)

def count_tokens(prompt: str, model_id: str) -> int:
    tok = _load_tokenizer(model_id)
    return len(tok(prompt, add_special_tokens=False).input_ids)

def prompt_export(table_details: list, database_description: str) -> list: 
    """
    Export the schema to a prompt format.
    """
    from core.templates import (
        SCHEMA_ENRICHMENT_SKELETON,
        TEXT_TO_SQL_SKELETON,
        TABLE_RETRIEVAL_SKELETON
    )
    list_prompt_skeleton = [
        SCHEMA_ENRICHMENT_SKELETON,
        TEXT_TO_SQL_SKELETON,
        TABLE_RETRIEVAL_SKELETON
    ] 

    schema = schema_parser(table_details, "DDL", include_sample_data=True)
    list_prompt = []
    for prompt_skeleton in list_prompt_skeleton:
        if prompt_skeleton == SCHEMA_ENRICHMENT_SKELETON:
            prompt_type = "schema_enrichment"
        elif prompt_skeleton == TEXT_TO_SQL_SKELETON:
            prompt_type = "text_to_sql"
        elif prompt_skeleton == TABLE_RETRIEVAL_SKELETON:
            prompt_type = "table_retrieval"

        prompt = prompt_skeleton.format(
            database_description=database_description,
            schema=schema,
            table_schemas=schema,
            dialect="postgres",
            user_question="What is the total number of users?",
            query="What is the total number of users?"
        )
        log_prompt(prompt, "Prompt Export")
        list_prompt.append({
            "prompt_type": prompt_type,
            "prompt": prompt,
            "token_count": count_tokens(prompt, "Qwen/Qwen2.5-Coder-14B")
        })

    return list_prompt