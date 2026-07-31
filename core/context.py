results = []
index = -1
query = None
app = None
folder = None
file = None


def remember_search(text, hits):
    global results, index, query
    query, results, index = text, list(hits), -1


def current():
    return results[index] if 0 <= index < len(results) else None


def step(delta):
    """Move through the last search's results, or None at either end."""
    global index
    new = index + delta
    if not results or not 0 <= new < len(results):
        return None
    index = new
    return results[index]


def clear():
    global results, index, query, app, folder, file
    results, index, query, app, folder, file = [], -1, None, None, None, None
