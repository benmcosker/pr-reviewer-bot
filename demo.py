def get_user(db, user_id):
    q = "SELECT * FROM users WHERE id = " + user_id
    return db.execute(q).fetchone()


def tally(items, seen={}):
    for i in items:
        seen[i] = seen.get(i, 0) + 1
    return seen
