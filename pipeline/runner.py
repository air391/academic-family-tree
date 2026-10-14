import argparse
import datetime
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from turso_client import TursoClient, upsert_persons, upsert_edges

try:
    import yaml
except ImportError:
    sys.exit("需要 PyYAML: pip install pyyaml")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), "sources.yaml")))
    client = None if args.dry_run else TursoClient()
    now = datetime.datetime.now().isoformat(timespec="seconds")

    for src in cfg["sources"]:
        if not src.get("enabled"):
            continue
        if args.source and src["name"] != args.source:
            continue
        print(f"[{src['name']}] adapter={src['adapter']} access={src['access_type']}")
        if src["access_type"] != "public":
            print(f"  跳过：{src['access_type']} 类型需手工导入或校内节点")
            continue

        mod = importlib.import_module(f"adapters.{src['adapter']}")
        adapter = mod.__dict__[[k for k in dir(mod) if k.endswith("Adapter")][0]](
            {**src.get("config", {}), "url": src.get("url", ""),
             "rate_limit_s": src.get("rate_limit_s", 1.0)})

        cursor = ""
        if client:
            rows = client.query(
                f"SELECT cursor FROM source_state WHERE source_name='{src['name']}'")
            cursor = rows[0][0] if rows else ""

        recs = list(adapter.fetch(cursor))
        persons, edges = adapter.to_persons_edges(recs)
        print(f"  本轮拉到 {len(recs)} 条 -> {len(persons)} 人 / {len(edges)} 边")

        if args.dry_run:
            continue
        upsert_persons(client, persons, now)
        upsert_edges(client, edges, now)

        new_cursor = adapter.next_cursor(cursor, recs) if hasattr(adapter, "next_cursor") else now[:10]
        client.exec([f"""INSERT INTO source_state(source_name,cursor,last_run_at,last_status,records_seen,records_new)
VALUES ('{src['name']}',{repr(new_cursor)},'{now}','success',{len(recs)},{len(recs)})
ON CONFLICT(source_name) DO UPDATE SET cursor=excluded.cursor,
last_run_at=excluded.last_run_at, last_status='success',
records_seen=records_seen+excluded.records_seen, records_new=excluded.records_new"""])
        print(f"  游标推进至 {new_cursor}")


if __name__ == "__main__":
    main()
