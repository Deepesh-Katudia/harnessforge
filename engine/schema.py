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
    "sales": {
        "saleDate": "date",
        "storeLocation": "string e.g. 'Denver', 'Seattle'",
        "purchaseMethod": "string 'In store' | 'Online' | 'Phone'",
        "couponUsed": "bool",
        "customer.gender": "string 'M' | 'F'",
        "customer.age": "int",
        "customer.email": "string",
        "customer.satisfaction": "int 1-5",
        "items": "array<{name:string, tags:array<string>, price:Decimal128, quantity:int}>",
        "items.name": "string",
        "items.price": "Decimal128 (unit price)",
        "items.quantity": "int",
    },
}

LOCATIONS = {"movies": "sample_mflix.movies", "comments": "sample_mflix.comments", "sales": "sample_supplies.sales"}


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
