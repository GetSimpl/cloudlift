def chunks(items, chunk_size):
    for i in range(0, len(items), chunk_size):
        yield items[i:i + chunk_size]
