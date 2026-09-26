"""Curated, concise schemas for allowlisted collections (what `get_schema` returns)."""
from __future__ import annotations

SCHEMAS: dict[str, dict[str, str]] = {
    "movies": {
        "title": "string",
        "year": "int (a few legacy docs hold strings)",
        "released": "date",
        "runtime": "int minutes",
        "genres": "array<string> e.g. ['Comedy','Drama']",
        "cast": "array<string> actor names",
        "directors": "array<string>",
        "writers": "array<string>",
        "countries": "array<string>",
        "languages": "array<string>",
        "rated": "string MPAA rating e.g. 'PG-13', 'R'",
        "type": "string 'movie' | 'series'",
        "imdb.rating": "double 0-10 (some docs hold '' empty string)",
        "imdb.votes": "int (some docs hold '' empty string)",
        "tomatoes.viewer.rating": "double 0-5",
        "tomatoes.viewer.numReviews": "int",
        "awards.wins": "int",
        "awards.nominations": "int",
        "num_mflix_comments": "int",
        "metacritic": "int 0-100 (often missing)",
    },
    "comments": {
        "name": "string commenter name",
        "email": "string",
        "movie_id": "ObjectId -> movies._id",
        "text": "string",
        "date": "date",
    },
    "accounts": {
        "account_id": "int",
        "limit": "int credit limit",
        "products": "array<string> e.g. ['Derivatives','InvestmentStock']",
    },
    "customers": {
        "username": "string",
        "name": "string",
        "email": "string",
        "birthdate": "date",
        "active": "bool (often missing)",
        "accounts": "array<int> account_id values -> accounts.account_id",
        "tier_and_details": "object keyed by random ids: {<id>: {tier, benefits[], active}}",
    },
    "transactions": {
        "account_id": "int -> accounts.account_id",
        "transaction_count": "int",
        "bucket_start_date": "date",
        "bucket_end_date": "date",
        "transactions": "array<{date, amount:int, transaction_code:'buy'|'sell', symbol:string, price, total}>",
        "transactions.date": "date",
        "transactions.amount": "int shares",
        "transactions.transaction_code": "string 'buy' | 'sell'",
        "transactions.symbol": "string ticker e.g. 'adbe'",
        "transactions.price": "string-encoded decimal",
        "transactions.total": "string-encoded decimal",
    },
}

LOCATIONS = {"movies": "sample_mflix.movies", "comments": "sample_mflix.comments", "accounts": "sample_analytics.accounts",
             "customers": "sample_analytics.customers", "transactions": "sample_analytics.transactions"}


def known_paths(collection: str) -> set[str]:
    paths = {"_id"}
    for path in SCHEMAS.get(collection, {}):
        parts = path.split(".")
        for i in range(1, len(parts) + 1):
            paths.add(".".join(parts[:i]))
    return paths


def render(collection: str | None = None) -> str:
    names = [collection] if collection else list(SCHEMAS)
    lines = []
    for name in names:
        lines.append(f"collection `{name}` ({LOCATIONS[name]}):")
        lines.extend(f"  - {field}: {typ}" for field, typ in SCHEMAS[name].items())
    return "\n".join(lines)
