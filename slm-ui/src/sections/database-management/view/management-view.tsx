import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';

import { useTheme } from '@mui/material/styles';
import {
  Box,
  Tab,
  Tabs,
  Stack,
  alpha,
  Tooltip,
  Container,
  Typography,
  IconButton,
  CircularProgress,
} from '@mui/material';

import axiosInstance, { endpoints } from 'src/utils/axios';

import Iconify from 'src/components/iconify';
import { DataSourceManagement } from 'src/components/text-to-sql/management';
import GroupManagement from 'src/components/text-to-sql/management/group-management';
import OwnerManagement from 'src/components/text-to-sql/management/owner-management';
import { TableDefinitionView } from 'src/components/text-to-sql/dialogs/table-definition-view';

import { DatabaseSource, TableDefinition, ColumnDefinition, RelationDefinition } from 'src/types/database';

// Custom TabPanel component
interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props;

  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`datasource-tabpanel-${index}`}
      aria-labelledby={`datasource-tab-${index}`}
      {...other}
      style={{ height: '100%' }}
    >
      {value === index && (
        <Box sx={{ height: '100%', pt: 3 }}>
          {children}
        </Box>
      )}
    </div>
  );
}

function a11yProps(index: number) {
  return {
    id: `datasource-tab-${index}`,
    'aria-controls': `datasource-tabpanel-${index}`,
  };
}

// Database type icons mapping
const DATABASE_ICONS = {
  mysql: 'logos:mysql',
  postgresql: 'logos:postgresql',
  sqlite: 'vscode-icons:file-type-sqlite',
  'microsoft sql server': 'simple-icons:microsoftsqlserver',
  oracle: 'logos:oracle',
};

export default function DatasourceManagementView() {
  const { id: sourceId } = useParams<{ id: string }>();
  const theme = useTheme();
  const navigate = useNavigate();
  const [value, setValue] = useState(0);
  const [loading, setLoading] = useState(true);
  const [dataSource, setDataSource] = useState<DatabaseSource | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Load datasource data
  useEffect(() => {
    const fetchDataSource = async () => {
      try {
        setLoading(true);
        const response = await axiosInstance.get(`${endpoints.dataSource.base}/${sourceId}`);
        setDataSource(response.data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'An error occurred');
      } finally {
        setLoading(false);
      }
    };

    if (sourceId) {
      fetchDataSource();
    }
  }, [sourceId]);

  useEffect(() => {
    console.log('DataSource updated:', dataSource);
  }, [dataSource]);

  const handleTabChange = (_: React.SyntheticEvent, newValue: number) => {
    setValue(newValue);
  };

  const handleDataSourceUpdate = async (updatedSource: DatabaseSource) => {
    if (!sourceId) return;
    
    // Refresh the data source to get the latest data including descriptions
    try {
      await axiosInstance.put(
        endpoints.dataSource.update(sourceId),
        {
          databaseDescription: updatedSource.databaseDescription || '',
        }
      );
      const response = await axiosInstance.get(`${endpoints.dataSource.base}/${sourceId}`);
      setDataSource(response.data);
    } catch (err) {
      console.error('Error updating data source:', err);
      setDataSource(updatedSource);
    }
  };

  const handleAutoFill = async (updatedTables: any, databaseDescription: string) => {
    try {
      await axiosInstance.put(endpoints.dataSource.tables.updateBatch(sourceId!), {
        tables: updatedTables,
      });
      await axiosInstance.put(endpoints.dataSource.update(sourceId!), {
        databaseDescription: databaseDescription || '',
      });
      const response = await axiosInstance.get(`${endpoints.dataSource.base}/${sourceId}`);
      setDataSource(response.data);
    } catch (err) {
      console.error('Error auto filling data source:', err);
    }
  };

  const handleDataSourceDelete = async (targetSourceId: string) => {
    try {
      await axiosInstance.delete(`${endpoints.dataSource.base}/${targetSourceId}`);
      // Navigate back or show success message
    } catch (deleteError) {
      console.error('Error deleting datasource:', deleteError);
    }
  };

  // Add relation handlers
  const handleRelationAdd = async (relation: RelationDefinition) => {
    try {
      if (!sourceId) return;

      const sourceTable = dataSource?.tableDefinitions.find((t: TableDefinition) => t.tableIdentifier === relation.sourceTableIdentifier);
      const sourceColumn = sourceTable?.columns.find((c: ColumnDefinition) => c.columnIdentifier === relation.sourceColumnIdentifier);

      if (!sourceTable || !sourceColumn) throw new Error('Source table or column not found');

      await axiosInstance.post(
        endpoints.dataSource.tables.columns.relations.base(
          sourceId,
          sourceTable.id.toString(),
          sourceColumn.id.toString()
        ),
        {
          tableIdentifier: relation.targetTableIdentifier,
          toColumn: relation.targetColumnIdentifier,
          type: relation.relationType
        }
      );

      // Refresh data source to get updated relations
      const response = await axiosInstance.get(`${endpoints.dataSource.base}/${sourceId}`);
      setDataSource(response.data);
    } catch (err) {
      console.error('Error adding relation:', err);
    }
  };

  const handleRelationUpdate = async (relation: RelationDefinition) => {
    try {
      if (!sourceId || !relation.id) return;

      const sourceTable = dataSource?.tableDefinitions.find((t: TableDefinition) => t.tableIdentifier === relation.sourceTableIdentifier);
      const sourceColumn = sourceTable?.columns.find((c: ColumnDefinition) => c.columnIdentifier === relation.sourceColumnIdentifier);
      const targetTable = dataSource?.tableDefinitions.find((t: TableDefinition) => t.tableIdentifier === relation.targetTableIdentifier);
      const targetColumn = targetTable?.columns.find((c: ColumnDefinition) => c.columnIdentifier === relation.targetColumnIdentifier);
      
      if (!sourceTable || !sourceColumn || !targetTable || !targetColumn) throw new Error('Source table or column not found');

      await axiosInstance.put(
        endpoints.dataSource.tables.columns.relations.update(
          sourceId,
          sourceTable.id.toString(),
          sourceColumn.id.toString(),
          relation.id
        ),
        { type: relation.relationType }
      );

      // Refresh data source to get updated relations
      const response = await axiosInstance.get(`${endpoints.dataSource.base}/${sourceId}`);
      setDataSource(response.data);
    } catch (err) {
      console.error('Error updating relation:', err);
      // Handle error (show notification, etc.)
    }
  };

  const handleRelationDelete = async (relation: RelationDefinition) => {
      if (!sourceId || !relation.id) throw new Error('Source ID or relation ID not found');

      const sourceTable = dataSource?.tableDefinitions.find((t: TableDefinition) => t.tableIdentifier === relation.sourceTableIdentifier);
      const sourceColumn = sourceTable?.columns.find((c: ColumnDefinition) => c.columnIdentifier === relation.sourceColumnIdentifier);

      if (!sourceTable || !sourceColumn) throw new Error('Source table or column not found');

      await axiosInstance.delete(
        endpoints.dataSource.tables.columns.relations.delete(
          sourceId,
          sourceTable.id.toString(),
          sourceColumn.id.toString(),
          relation.id
        )
      );

      // Refresh data source to get updated relations
      const response = await axiosInstance.get(`${endpoints.dataSource.base}/${sourceId}`);
      setDataSource(response.data);
  };

  if (loading) {
    return (
      <Box
        sx={{
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <CircularProgress />
      </Box>
    );
  }

  if (error || !dataSource) {
    return (
      <Box
        sx={{
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Typography color="error">
          {error || 'Datasource not found'}
        </Typography>
      </Box>
    );
  }

  return (
    <Container maxWidth={false} sx={{ height: '100%' }}>
      <Stack spacing={3} sx={{ height: '100%' }}>
        <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
          <Stack
            direction="row"
            alignItems="center"
            spacing={2}
            sx={{ mb: 3 }}
          >
            <Tooltip title="Back to home">
              <IconButton
                onClick={() => navigate('/')}
                sx={{
                  mr: 1,
                  color: 'text.secondary',
                  '&:hover': {
                    color: 'primary.main',
                    bgcolor: (t) => alpha(t.palette.primary.main, 0.08),
                  },
                }}
              >
                <Iconify icon="eva:arrow-ios-back-fill" width={24} height={24} />
              </IconButton>
            </Tooltip>
            <Box
              sx={{
                p: 1,
                borderRadius: '50%',
                bgcolor: (t) => alpha(t.palette.primary.main, 0.1),
              }}
            >
              <Iconify
                icon={DATABASE_ICONS[dataSource.databaseType.toLowerCase() as keyof typeof DATABASE_ICONS] || 'eva:database-fill'}
                width={24}
                height={24}
                sx={{ color: 'primary.main' }}
              />
            </Box>
            <Typography variant="h4">
              {dataSource.name}
            </Typography>
          </Stack>

          <Tabs
            value={value}
            onChange={handleTabChange}
            aria-label="datasource management tabs"
            sx={{
              '& .MuiTab-root': {
                minHeight: 48,
                minWidth: 120,
                fontWeight: 600,
                borderTopLeftRadius: 8,
                borderTopRightRadius: 8,
                '&.Mui-selected': {
                  color: theme.palette.primary.main,
                },
              },
            }}
          >
            <Tab
              label="Information"
              {...a11yProps(0)}
              icon={<Iconify icon="eva:info-fill" width={20} height={20} />}
              iconPosition="start"
            />
            <Tab
              label="Access Groups"
              {...a11yProps(1)}
              icon={<Iconify icon="eva:people-fill" width={20} height={20} />}
              iconPosition="start"
            />
            <Tab
              label="Owners"
              {...a11yProps(2)}
              icon={<Iconify icon="eva:shield-fill" width={20} height={20} />}
              iconPosition="start"
            />
            <Tab
              label="Schema"
              {...a11yProps(3)}
              icon={<Iconify icon="eva:grid-fill" width={20} height={20} />}
              iconPosition="start"
            />
          </Tabs>
        </Box>

        <Box sx={{ flexGrow: 1, minHeight: 0 }}>
          <TabPanel value={value} index={0}>
            <DataSourceManagement
              dataSource={dataSource}
              onUpdate={handleDataSourceUpdate}
              onDelete={handleDataSourceDelete}
            />
          </TabPanel>
          
          <TabPanel value={value} index={1}>
            <GroupManagement
              sourceId={sourceId!}
              tables={dataSource.tableDefinitions.map(t => ({ id: t.id, tableIdentifier: t.tableIdentifier }))}
              onGroupsChange={() => {
                // Refresh data if needed
              }}
            />
          </TabPanel>

          <TabPanel value={value} index={2}>
            <OwnerManagement
              sourceId={sourceId!}
              onOwnersChange={() => {
                // Refresh data if needed
              }}
            />
          </TabPanel>
          
          <TabPanel value={value} index={3}>
            <TableDefinitionView
              tables={dataSource.tableDefinitions}
              databaseDescription={dataSource.databaseDescription}
              onDatabaseDescriptionUpdate={(description) => {
                handleDataSourceUpdate({
                  ...dataSource,
                  databaseDescription: description,
                });
              }}
              onAutoFill={(updatedTables, databaseDescription) => {
                handleAutoFill(updatedTables, databaseDescription);
              }}
              onRelationAdd={handleRelationAdd}
              onRelationUpdate={handleRelationUpdate}
              onRelationDelete={handleRelationDelete}
              connectionPayload={{
                url: `${dataSource.host}:${dataSource.port}/${dataSource.databaseName}`,
                username: dataSource.username,
                password: dataSource.password,
                dbType: dataSource.databaseType.toLowerCase() as 'mysql' | 'postgresql'
              }}
            />
          </TabPanel>
        </Box>
      </Stack>
    </Container>
  );
}
