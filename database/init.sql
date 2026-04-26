-- ────────────────────────────────────────────────────────────────────────────
-- Skillify Database Schema
-- FIXED: jobs table now includes `domain` and `scraped_at` columns
--        with an index on (domain, scraped_at) for fast date-filtered queries.
-- ────────────────────────────────────────────────────────────────────────────

CREATE DATABASE IF NOT EXISTS skillify;
USE skillify;

CREATE TABLE Users (
    user_id       INT AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(100)  NOT NULL,
    email         VARCHAR(255)  UNIQUE NOT NULL,
    password_hash VARCHAR(255)  NOT NULL,
    role          ENUM('student', 'admin') DEFAULT 'student',
    created_at    TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE User_Profile (
    profile_id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id                 INT          NOT NULL,
    education               VARCHAR(500),
    experience_level        ENUM('beginner', 'intermediate', 'advanced', 'expert'),
    domain_interest         VARCHAR(255),
    profile_completion_score INT         DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES Users(user_id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id)
);

CREATE TABLE Skills (
    skill_id   INT AUTO_INCREMENT PRIMARY KEY,
    skill_name VARCHAR(100) NOT NULL UNIQUE,
    skill_type ENUM('technical', 'soft')
);

CREATE TABLE User_Skills (
    user_id          INT NOT NULL,
    skill_id         INT NOT NULL,
    proficiency_level ENUM('beginner', 'intermediate', 'advanced'),
    source           ENUM('resume', 'assessment'),
    PRIMARY KEY (user_id, skill_id),
    FOREIGN KEY (user_id)  REFERENCES Users(user_id)  ON DELETE CASCADE,
    FOREIGN KEY (skill_id) REFERENCES Skills(skill_id) ON DELETE CASCADE
);

CREATE TABLE User_Company_Record (
    record_id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id            INT          NOT NULL,
    company_name       VARCHAR(200) NOT NULL,
    role_title         VARCHAR(200) NOT NULL,
    match_score        INT          NOT NULL,
    gap_severity       ENUM('low', 'medium', 'high'),
    application_status ENUM('viewed', 'saved', 'applied'),
    created_at         TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES Users(user_id) ON DELETE CASCADE
);

CREATE TABLE Trending_Skills (
    skill_id     INT PRIMARY KEY,
    demand_score INT       NOT NULL,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (skill_id) REFERENCES Skills(skill_id) ON DELETE CASCADE
);

-- ── Jobs table ───────────────────────────────────────────────────────────────
-- `domain`     — keyword-based tag set by the scraper (e.g. 'frontend', 'data')
-- `scraped_at` — when this row was written; used by date_filter in production
CREATE TABLE IF NOT EXISTS jobs (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    source     VARCHAR(50)   NOT NULL,
    title      VARCHAR(255)  NOT NULL,
    company    VARCHAR(255),
    location   VARCHAR(255),
    link       VARCHAR(700)  UNIQUE NOT NULL,
    skills     TEXT,
    domain     VARCHAR(50)   DEFAULT '',
    scraped_at TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,

    -- Fast lookup by domain + recency (powers the date_filter in production)
    INDEX idx_domain_scraped (domain, scraped_at),
    INDEX idx_location       (location(100))
);


-- ── ONE-TIME CLEANUP: remove duplicate jobs keeping only the freshest row ────
-- Run this once manually on your live TiDB to clear existing dirty data.
-- After this, run_background_scraper.py's new logic prevents re-accumulation.
--
-- DELETE j1 FROM jobs j1
-- INNER JOIN jobs j2
--   ON  LOWER(j1.title)   = LOWER(j2.title)
--   AND LOWER(j1.company) = LOWER(j2.company)
--   AND j1.domain         = j2.domain
--   AND j1.scraped_at     < j2.scraped_at;
