package com.slm.slmbackend.dto.datasource;

import com.slm.slmbackend.enums.DatabaseType;
import lombok.Data;

@Data
public class DataSourceConfigurationDTO {
    private Integer id;
    private DatabaseType databaseType;
    private String name;
    private String host;
    private Integer port;
    private String databaseName;
    private String username;
    private String password;
    private String databaseDescription;
}