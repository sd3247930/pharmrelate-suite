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
-- parentCode 完整性
--
-- 单表方案下 parent_code 只是文本，光靠 CHECK 只能保证"有没有父"，
-- 不能保证"父真的存在"。下面两个触发器补上这一层，并顺带强制导出顺序：
--   1. 父码必须存在于同一批次；
--   2. 父的层级必须是 当前层级 + 1（罐的父是箱，粒子的父是罐）；
--   3. 父必须排在子之前（seq 更小）—— 这正是 XML 基准要求的
--      "箱 → 罐 → 该罐的粒子"顺序，把它交给数据库守，而不是靠调用方自觉；
--   4. 顺带排除自己当自己的父（父的 seq 不可能小于自身）。
-- ---------------------------------------------------------------------------
CREATE TRIGGER IF NOT EXISTS trg_code_parent_insert
BEFORE INSERT ON code
FOR EACH ROW
WHEN NEW.parent_code IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'parentCode 无效：父码必须存在于同批次、层级正确且排在子码之前')
    WHERE NOT EXISTS (
        SELECT 1
        FROM code AS parent
        WHERE parent.batch_id  = NEW.batch_id
          AND parent.cur_code  = NEW.parent_code
          AND parent.deleted   = 0
          AND parent.pack_layer = NEW.pack_layer + 1
          AND parent.seq       < NEW.seq
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_code_parent_update
BEFORE UPDATE OF parent_code, seq, pack_layer, batch_id, deleted ON code
FOR EACH ROW
WHEN NEW.parent_code IS NOT NULL AND NEW.deleted = 0
BEGIN
    SELECT RAISE(ABORT, 'parentCode 无效：父码必须存在于同批次、层级正确且排在子码之前')
    WHERE NOT EXISTS (
        SELECT 1
        FROM code AS parent
        WHERE parent.batch_id  = NEW.batch_id
          AND parent.cur_code  = NEW.parent_code
          AND parent.deleted   = 0
          AND parent.pack_layer = NEW.pack_layer + 1
          AND parent.seq       < NEW.seq
          AND parent.id        <> NEW.id
    );
END;

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
-- 包装结构计划
--
-- 界面 2 定的是"计划"（几罐、每罐几粒），界面 3 才产出"实际"（箱号/罐号/粒子码）。
-- 两者必须分开存：
--   - 计划在扫码之前就存在，而 code 表的 cur_code 不允许为空，
--     所以计划没法用 code 行表达；
--   - code 表只承载已经扫到的真实条码，这样"计划 vs 实际"的核对才有意义。
-- code.planned_particle_count 保留为扫描时的冗余快照，便于单表核对。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS can_plan (
    batch_id               TEXT NOT NULL REFERENCES batch (id) ON DELETE CASCADE,
    can_index              INTEGER NOT NULL CHECK (can_index >= 1 AND can_index <= 5),
    planned_particle_count INTEGER NOT NULL CHECK (planned_particle_count >= 1 AND planned_particle_count <= 2500),
    PRIMARY KEY (batch_id, can_index)
);

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
