package com.slm.slmbackend.enums;

import lombok.Getter;

@Getter
public enum ResponseEnum {
    UNAUTHORIZED(401, "Unauthorized"),
    FORBIDDEN(403, "Forbidden"),
    NOT_FOUND(404, "Not Found"),
    INTERNAL_SERVER_ERROR(500, "Internal Server Error"),
    INVALID_USERNAME_OR_PASSWORD(401, "Invalid username or password"),
    USERNAME_ALREADY_EXISTS(400, "Username already exists"),
    TOKEN_EXPIRED(401, "Token expired"),
    TOKEN_INVALID(401, "Token invalid"),
    USER_NOT_FOUND(404, "User not found"),


    SUCCESS(0, "Success"),
    DATA_SOURCE_CONFIGURATION_NOT_FOUND(1, "Data source configuration not found"),
    DATA_SOURCE_NOT_BELONG_TO_USER(2, "Data source does not belong to user"),
    COLUMN_IN_RELATION_NOT_FOUND(3, "Column in relation not found"),
    TABLE_NOT_FOUND(4, "Table not found"),
    COLUMN_NOT_FOUND(5, "Column not found"),
    RELATION_NOT_FOUND(6, "Relation not found"),
    RELATION_NOT_BELONG_TO_COLUMN(7, "Relation does not belong to column"),
    DATASOURCE_CONNECT_FAILED(8, "Data source connection failed"),
    CHAT_SESSION_NOT_FOUND(9, "Chat session not found"),
    CHAT_SESSION_NOT_BELONG_TO_USER(10, "Chat session does not belong to user"),
    INVALID_REQUEST(11, "Invalid request"),
    REQUEST_TIMEOUT(12, "Request timeout"),
    CANNOT_REMOVE_OWNER_FROM_DATA_SOURCE(13, "Cannot remove yourself as owner from data source"),
    DATA_SOURCE_MUST_HAVE_AT_LEAST_ONE_OWNER(14, "Data source must have at least one owner");

    private final int code;
    private final String message;

    ResponseEnum(int code, String message) {
        this.code = code;
        this.message = message;
    }

}
