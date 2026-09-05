-- SPDX-License-Identifier: MIT
-- DATA-001: Fable 5.1 output, reviewed by Codex.
-- Storage contract only. BLOB does not imply encryption: a separate reviewed
-- native adapter must encrypt before insertion and authenticate on reading.
-- One database per opaque local account generation. Peer ids/timestamps are
-- metadata visible in SQLite. No real user data until crypto/lifecycle pass QA.
-- Runner must refuse nonempty DBs or user_version != 0 before applying.
BEGIN;
CREATE TABLE notes (
    id INTEGER PRIMARY KEY,
    peer_type TEXT NOT NULL CHECK (peer_type IN ('user','chat','channel')),
    peer_id INTEGER NOT NULL CHECK (typeof(peer_id)='integer' AND peer_id>0),
    topic_id INTEGER NOT NULL DEFAULT 0
        CHECK (typeof(topic_id)='integer' AND topic_id>=0),
    payload BLOB NOT NULL
        CHECK (typeof(payload)='blob' AND length(payload)>=1 AND length(payload)<=131072),
    created_at INTEGER NOT NULL CHECK (typeof(created_at)='integer' AND created_at>=0),
    updated_at INTEGER NOT NULL CHECK (typeof(updated_at)='integer' AND updated_at>=created_at),
    CHECK (topic_id=0 OR peer_type='channel'),
    UNIQUE (peer_type,peer_id,topic_id)
);
CREATE TABLE templates (
    id INTEGER PRIMARY KEY,
    payload BLOB NOT NULL
        CHECK (typeof(payload)='blob' AND length(payload)>=1 AND length(payload)<=131072),
    sort_order INTEGER NOT NULL DEFAULT 0
        CHECK (typeof(sort_order)='integer' AND sort_order>=0),
    created_at INTEGER NOT NULL CHECK (typeof(created_at)='integer' AND created_at>=0),
    updated_at INTEGER NOT NULL CHECK (typeof(updated_at)='integer' AND updated_at>=created_at)
);
CREATE INDEX templates_sort_order_idx ON templates(sort_order,id);
PRAGMA user_version=1;
COMMIT;
