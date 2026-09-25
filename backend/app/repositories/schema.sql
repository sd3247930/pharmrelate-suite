-- 籽关通 (PharmRelate Multi) 本地库 schema
--
-- 设计说明：条码统一存放在单张 `code` 表里，而不是拆成 box / can / particle 三张表。
-- 理由：
--   1. XML 本身就是一串扁平的 <Code packLayer parentCode> 节点，单表与导出结构一一对应；
--   2. V1.1 要求"同批次内 code 全局唯一"，只有单表才能用一条 UNIQUE 约束真正强制它，
--      拆表则只能靠应用层检查，而应用层检查正是约束要取代的东西；
--   3. 层级关系由 pack_layer + parent_code 表达，用 CHECK 约束即可保证箱无父、罐/粒子必须有父。
-- 为便于按层级阅读，另建 v_box / v_can / v_particle 三个视图。

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- 批次
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS batch (
    id                     TEXT PRIMARY KEY,

    -- 业务信息
    batch_no               TEXT NOT NULL,
    made_date              TEXT NOT NULL,
    validate_date          TEXT NOT NULL,
    status                 TEXT NOT NULL,

    -- 程序固定参数（落库保存，保证历史批次导出结果可复现）
    product_code           TEXT NOT NULL,
    sub_type_no            TEXT NOT NULL,
    cascade                TEXT NOT NULL,
    package_spec           TEXT NOT NULL,
    comment                TEXT NOT NULL,
    flag                   TEXT NOT NULL,
    workshop               TEXT NOT NULL,
    line_name              TEXT NOT NULL,
    line_manager           TEXT NOT NULL,
    license                TEXT NOT NULL,

    -- 提前结束签名（V1.1 10.5；签名形式：操作人下拉 + 备注文本）
    early_end_reason       TEXT,
    early_end_operator     TEXT,
    early_end_note         TEXT,
    early_end_at           TEXT,
    early_end_can_count    INTEGER,
    early_end_particle_count INTEGER,

    -- SyncMeta（二期同步使用，一期先落字段）
    revision               INTEGER NOT NULL DEFAULT 1,
    hlc                    TEXT NOT NULL DEFAULT '',
    updated_by             TEXT NOT NULL DEFAULT 'local-user',
    device_id              TEXT NOT NULL DEFAULT 'windows-main',
    deleted                INTEGER NOT NULL DEFAULT 0,

    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL
);

-- 批号唯一：软删除的记录不参与唯一性判定
CREATE UNIQUE INDEX IF NOT EXISTS ux_batch_batch_no
    ON batch (batch_no) WHERE deleted = 0;

CREATE INDEX IF NOT EXISTS ix_batch_status ON batch (status);
CREATE INDEX IF NOT EXISTS ix_batch_updated_at ON batch (updated_at DESC);

-- ---------------------------------------------------------------------------
-- 条码（箱 packLayer=3 / 罐 packLayer=2 / 粒子 packLayer=1）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS code (
    id                     TEXT PRIMARY KEY,
    batch_id               TEXT NOT NULL REFERENCES batch (id) ON DELETE CASCADE,

    cur_code               TEXT NOT NULL,
    pack_layer             INTEGER NOT NULL CHECK (pack_layer IN (1, 2, 3)),
    parent_code            TEXT,

    -- 导出顺序：必须保持采集原始顺序，禁止按 code 排序
    seq                    INTEGER NOT NULL,

    -- 仅 pack_layer = 2（罐）有意义
    planned_particle_count INTEGER,

    -- SyncMeta
    revision               INTEGER NOT NULL DEFAULT 1,
    hlc                    TEXT NOT NULL DEFAULT '',
    updated_by             TEXT NOT NULL DEFAULT 'local-user',
    device_id              TEXT NOT NULL DEFAULT 'windows-main',
    deleted                INTEGER NOT NULL DEFAULT 0,

    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,

    -- 箱没有父；罐与粒子必须有父
    CHECK (
        (pack_layer = 3 AND parent_code IS NULL)
        OR (pack_layer IN (1, 2) AND parent_code IS NOT NULL)
    ),
    -- 计划粒子数只对罐生效
    CHECK (
        (pack_layer = 2 AND planned_particle_count IS NOT NULL)
        OR (pack_layer <> 2 AND planned_particle_count IS NULL)
    ),
    CHECK (cur_code <> ''),
    CHECK (seq >= 0)
);

-- 同批次内条码全局唯一（V1.1 防重复扫码的底线保障）
CREATE UNIQUE INDEX IF NOT EXISTS ux_code_batch_code
    ON code (batch_id, cur_code) WHERE deleted = 0;

CREATE INDEX IF NOT EXISTS ix_code_batch_layer_seq ON code (batch_id, pack_layer, seq);
CREATE INDEX IF NOT EXISTS ix_code_parent ON code (batch_id, parent_code);

-- ---------------------------------------------------------------------------
-- 按层级阅读的视图
-- ---------------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_box AS
    SELECT * FROM code WHERE pack_layer = 3 AND deleted = 0;

CREATE VIEW IF NOT EXISTS v_can AS
    SELECT * FROM code WHERE pack_layer = 2 AND deleted = 0;

CREATE VIEW IF NOT EXISTS v_particle AS
    SELECT * FROM code WHERE pack_layer = 1 AND deleted = 0;

-- ---------------------------------------------------------------------------
-- 二期预留：操作日志与审计日志
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oplog (
    op_id                  TEXT PRIMARY KEY,
    batch_id               TEXT NOT NULL,
    entity                 TEXT NOT NULL CHECK (entity IN ('batch', 'box', 'can', 'particle')),
    entity_id              TEXT NOT NULL,
    action                 TEXT NOT NULL CHECK (action IN ('create', 'update', 'delete', 'replace')),
    field                  TEXT,
    old_value              TEXT,
    new_value              TEXT,
    hlc                    TEXT NOT NULL,
    device_id              TEXT NOT NULL,
    user_id                TEXT NOT NULL,
    timestamp              TEXT NOT NULL,
    synced                 INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_oplog_batch ON oplog (batch_id, hlc);
CREATE INDEX IF NOT EXISTS ix_oplog_synced ON oplog (synced, hlc);

CREATE TABLE IF NOT EXISTS audit_log (
    log_id                 TEXT PRIMARY KEY,
    user_id                TEXT NOT NULL,
    device_id              TEXT NOT NULL,
    timestamp              TEXT NOT NULL,
    action                 TEXT NOT NULL,
    entity                 TEXT NOT NULL,
    entity_id              TEXT NOT NULL,
    old_value              TEXT,
    new_value              TEXT,
    result                 TEXT NOT NULL,
    reason                 TEXT
);

CREATE INDEX IF NOT EXISTS ix_audit_entity ON audit_log (entity, entity_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS ix_audit_timestamp ON audit_log (timestamp DESC);

-- ---------------------------------------------------------------------------
-- 元数据（schema 版本，供后续迁移使用）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meta (
    key                    TEXT PRIMARY KEY,
    value                  TEXT NOT NULL
);
