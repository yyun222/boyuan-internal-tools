-- Author: liuzhiwei_jn
-- Date: 2026-11-18
-- Version: v1.0.0
-- 在现有本系统数据库中手工执行，先选择正确的数据库。MySQL 5.7 / 8.0。
-- 不创建业务账号、不填充手机号、不更改已有权限。升级前先备份。

SET @oa_phone_column_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'oa_login_phone'
);
SET @oa_ddl = IF(@oa_phone_column_exists = 0,
    'ALTER TABLE `users` ADD COLUMN `oa_login_phone` VARCHAR(11) NULL COMMENT ''OA 登录手机号''',
    'SELECT ''oa_login_phone already exists'' AS result');
PREPARE oa_statement FROM @oa_ddl;
EXECUTE oa_statement;
DEALLOCATE PREPARE oa_statement;

SET @oa_phone_unique_exists = (
    SELECT COUNT(*) FROM (
        SELECT INDEX_NAME FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND NON_UNIQUE = 0
        GROUP BY INDEX_NAME
        HAVING COUNT(*) = 1 AND MAX(COLUMN_NAME) = 'oa_login_phone' AND MAX(SUB_PART) IS NULL
    ) AS oa_unique_indexes
);
SET @oa_ddl = IF(@oa_phone_unique_exists = 0,
    'ALTER TABLE `users` ADD UNIQUE KEY `uq_users_oa_login_phone` (`oa_login_phone`)',
    'SELECT ''oa_login_phone unique index already exists'' AS result');
PREPARE oa_statement FROM @oa_ddl;
EXECUTE oa_statement;
DEALLOCATE PREPARE oa_statement;

CREATE TABLE IF NOT EXISTS `oa_sso_credentials` (
    `nonce_hash` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `expires_at` DATETIME NOT NULL,
    `consumed_at` DATETIME NOT NULL,
    PRIMARY KEY (`nonce_hash`),
    KEY `ix_oa_sso_credentials_expires_at` (`expires_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 验证结构；脚本可重复执行。若唯一索引创建失败，请先核查已有重复手机号。
SHOW COLUMNS FROM `users` LIKE 'oa_login_phone';
SHOW INDEX FROM `users` WHERE Column_name = 'oa_login_phone';
SHOW CREATE TABLE `oa_sso_credentials`;
