from engine import db
rows = db.execute("SELECT id, title, LENGTH(content) as content_len FROM fds_documents WHERE id = 5")
if rows:
    print(f"FDS ID 5: {rows[0]['title']}")
    print(f"Content length in DB: {rows[0]['content_len']} characters")
else:
    print("FDS ID 5 not found")

rows_reqs = db.execute("SELECT COUNT(*) as count FROM fds_requirements WHERE fds_id = 5")
print(f"Requirements count in DB: {rows_reqs[0]['count']}")
