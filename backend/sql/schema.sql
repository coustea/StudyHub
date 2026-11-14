
-- ============================================================
-- FrameForge Database Schema
-- MySQL 8.0+
-- Charset: utf8mb4
-- Collation: utf8mb4_unicode_ci
--
-- Tables:
--   1. users     用户
--   2. projects  视频项目
--   3. messages  对话消息
--   4. tasks     视频生成与修改任务
-- ============================================================

CREATE DATABASE IF NOT EXISTS `frameforge`
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE `frameforge`;


-- ============================================================
-- 1. users 用户表
-- ============================================================

CREATE TABLE IF NOT EXISTS `users` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    `username` VARCHAR(64) NOT NULL,
    `email` VARCHAR(255) NOT NULL,
    `password_hash` VARCHAR(255) NOT NULL,

    `display_name` VARCHAR(100) NULL,
    `avatar_url` VARCHAR(512) NULL,

    `role` VARCHAR(20) NOT NULL DEFAULT 'user',
    `is_active` TINYINT(1) NOT NULL DEFAULT 1,

    `last_login_at` DATETIME(6) NULL,

    `created_at` DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    `updated_at` DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (`id`),

    UNIQUE KEY `uq_users_username` (`username`),
    UNIQUE KEY `uq_users_email` (`email`),

    KEY `idx_users_role_active` (`role`, `is_active`)

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;


-- ============================================================
-- 2. projects 视频项目表
-- 一个项目对应一份视频工程和一条持续对话
-- ============================================================

CREATE TABLE IF NOT EXISTS `projects` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    `user_id` BIGINT UNSIGNED NOT NULL,

    `title` VARCHAR(200) NOT NULL,

    -- 当前已发布的视频版本
    -- 0 表示尚未成功生成视频
    `current_revision` INT UNSIGNED NOT NULL DEFAULT 0,

    `created_at` DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    `updated_at` DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (`id`),

    KEY `idx_projects_user_updated`
        (`user_id`, `updated_at`),

    CONSTRAINT `fk_projects_user`
        FOREIGN KEY (`user_id`)
        REFERENCES `users` (`id`)
        ON DELETE CASCADE

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;


-- ============================================================
-- 3. messages 对话消息表
-- 保存用户需求、Agent 回复以及后续截图修改上下文
-- ============================================================

CREATE TABLE IF NOT EXISTS `messages` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    `project_id` BIGINT UNSIGNED NOT NULL,

    -- user / assistant
    `role` VARCHAR(20) NOT NULL,

    `content` TEXT NOT NULL,

    -- 可选上下文：
    -- screenshot、scene_id、timestamp_ms、revision 等
    `metadata` JSON NULL,

    `created_at` DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (`id`),

    KEY `idx_messages_project_id`
        (`project_id`, `id`),

    CONSTRAINT `fk_messages_project`
        FOREIGN KEY (`project_id`)
        REFERENCES `projects` (`id`)
        ON DELETE CASCADE,

    CONSTRAINT `chk_messages_role`
        CHECK (`role` IN ('user', 'assistant'))

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;


-- ============================================================
-- 4. tasks 视频任务表
-- 一条任务对应一次 LangGraph 工作流执行
--
-- create:
--   Plan -> Code -> Validate -> Repair -> Render
--
-- edit:
--   Code -> Validate -> Repair -> Render
-- ============================================================

CREATE TABLE IF NOT EXISTS `tasks` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    `project_id` BIGINT UNSIGNED NOT NULL,

    -- 触发本次任务的用户消息
    `request_message_id` BIGINT UNSIGNED NULL,

    -- create / edit
    `type` VARCHAR(20) NOT NULL DEFAULT 'create',

    -- pending / running / success / failed / cancelled
    `status` VARCHAR(20) NOT NULL DEFAULT 'pending',

    -- pending / plan / code / validate / repair / render / completed
    `phase` VARCHAR(30) NOT NULL DEFAULT 'pending',

    -- 任务进度：0 - 100
    `progress` TINYINT UNSIGNED NOT NULL DEFAULT 0,

    -- 本次任务基于的工程版本
    `base_revision` INT UNSIGNED NOT NULL DEFAULT 0,

    -- 成功生成的版本，失败时为 NULL
    `result_revision` INT UNSIGNED NULL,

    -- 任务失败原因
    `error_message` TEXT NULL,

    `created_at` DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    `started_at` DATETIME(6) NULL,
    `finished_at` DATETIME(6) NULL,

    `updated_at` DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),

    PRIMARY KEY (`id`),

    KEY `idx_tasks_project_created`
        (`project_id`, `created_at`),

    KEY `idx_tasks_status_created`
        (`status`, `created_at`),

    KEY `idx_tasks_request_message`
        (`request_message_id`),

    CONSTRAINT `fk_tasks_project`
        FOREIGN KEY (`project_id`)
        REFERENCES `projects` (`id`)
        ON DELETE CASCADE,

    CONSTRAINT `fk_tasks_request_message`
        FOREIGN KEY (`request_message_id`)
        REFERENCES `messages` (`id`)
        ON DELETE SET NULL,

    CONSTRAINT `chk_tasks_type`
        CHECK (`type` IN ('create', 'edit')),

    CONSTRAINT `chk_tasks_status`
        CHECK (`status` IN (
            'pending',
            'running',
            'success',
            'failed',
            'cancelled'
        )),

    CONSTRAINT `chk_tasks_progress`
        CHECK (`progress` BETWEEN 0 AND 100)

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;
