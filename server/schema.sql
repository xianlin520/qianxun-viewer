-- 千寻影集服务端 D1 schema
-- 应用方式：npx wrangler d1 execute qx-album --remote --file=./schema.sql

CREATE TABLE IF NOT EXISTS shares (
  token       TEXT PRIMARY KEY,          -- 7 位 base62 随机 token
  oss_key     TEXT NOT NULL,             -- 完整对象 key，如 qx/113657748_p0.png
  bucket      TEXT NOT NULL,             -- 所属桶（多桶时用）
  note        TEXT,                      -- 可选备注（客户端填）
  created_at  INTEGER NOT NULL,          -- 创建时间 epoch ms
  revoked     INTEGER NOT NULL DEFAULT 0,-- 0 有效 / 1 已撤销
  revoked_at  INTEGER,                   -- 撤销时间
  hits        INTEGER NOT NULL DEFAULT 0,-- 累计访问次数
  first_hit   INTEGER,                   -- 首次访问
  last_hit    INTEGER                    -- 最后访问
);

CREATE INDEX IF NOT EXISTS idx_shares_key     ON shares(oss_key);
CREATE INDEX IF NOT EXISTS idx_shares_revoked ON shares(revoked);

-- 收藏列表同步（LWW：updated_at 大者胜）
CREATE TABLE IF NOT EXISTS favorites (
  oss_key    TEXT PRIMARY KEY,           -- 图片相对路径（跨机一致的标识）
  favorite   INTEGER NOT NULL,           -- 0/1
  updated_at INTEGER NOT NULL            -- LWW 时间戳 epoch ms
);

CREATE INDEX IF NOT EXISTS idx_fav_updated ON favorites(updated_at);
