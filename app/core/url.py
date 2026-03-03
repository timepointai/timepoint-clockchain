import re
import unicodedata

MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]
MONTH_TO_NUM = {m: i + 1 for i, m in enumerate(MONTHS)}
NUM_TO_MONTH = {i + 1: m for i, m in enumerate(MONTHS)}

PATH_SEGMENTS = ["year", "month", "day", "time", "country", "region", "city", "slug"]


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text.strip("-")


def build_path(
    year: int,
    month: int,
    day: int,
    time: str,
    country: str,
    region: str,
    city: str,
    slug: str,
) -> str:
    month_name = NUM_TO_MONTH.get(month, "")
    country_slug = slugify(country)
    region_slug = slugify(region)
    city_slug = slugify(city)
    slug_clean = slugify(slug) if slug else ""
    return f"/{year}/{month_name}/{day}/{time}/{country_slug}/{region_slug}/{city_slug}/{slug_clean}"


def parse_path(path: str) -> dict | None:
    path = path.strip("/")
    parts = path.split("/")
    if len(parts) != 8:
        return None
    try:
        year = int(parts[0])
        month_str = parts[1].lower()
        month = MONTH_TO_NUM.get(month_str)
        if month is None:
            return None
        day = int(parts[2])
        time_str = parts[3]
        country = parts[4]
        region = parts[5]
        city = parts[6]
        slug = parts[7]
        return {
            "year": year,
            "month": month,
            "month_name": month_str,
            "day": day,
            "time": time_str,
            "country": country,
            "region": region,
            "city": city,
            "slug": slug,
        }
    except (ValueError, IndexError):
        return None


def parse_partial_path(path: str) -> dict[str, int | str]:
    path = path.strip("/")
    if not path:
        return {}
    parts = path.split("/")
    result: dict[str, int | str] = {}
    for i, segment in enumerate(parts):
        if i >= len(PATH_SEGMENTS):
            break
        key = PATH_SEGMENTS[i]
        if key == "year":
            try:
                result[key] = int(segment)
            except ValueError:
                result[key] = segment
        elif key == "month":
            result[key] = segment.lower()
            m = MONTH_TO_NUM.get(segment.lower())
            if m is not None:
                result["month_num"] = m
        elif key == "day":
            try:
                result[key] = int(segment)
            except ValueError:
                result[key] = segment
        else:
            result[key] = segment
    return result
