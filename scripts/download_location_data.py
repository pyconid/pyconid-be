from pathlib import Path
import gzip
import httpx


def download_location_data():
    base_url = "https://raw.githubusercontent.com/dr5hn/countries-states-cities-database/master/json"
    data_dir = Path("seeders/data/location")
    data_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "countries.json": {
            "url": f"{base_url}/countries.json",
            "gzip": False,
        },
        "states.json": {
            "url": f"{base_url}/states.json",
            "gzip": False,
        },
        "countries+states+cities.json": {
            "url": f"{base_url}/countries+states+cities.json",
            "gzip": True,
        },
    }

    try:
        with httpx.Client(follow_redirects=True, timeout=120) as client:
            for filename, config in files.items():
                raw_path = data_dir / filename
                path = (
                    raw_path.with_suffix(raw_path.suffix + ".gz")
                    if config["gzip"]
                    else raw_path
                )

                print(f"Downloading {filename}...")

                with client.stream("GET", config["url"]) as r:
                    r.raise_for_status()
                    if config["gzip"]:
                        with gzip.open(path, "wb") as f:
                            for chunk in r.iter_bytes():
                                f.write(chunk)
                    else:
                        with open(path, "wb") as f:
                            for chunk in r.iter_bytes():
                                f.write(chunk)

                if config["gzip"] and raw_path.exists():
                    raw_path.unlink()

                size_mb = path.stat().st_size / (1024 * 1024)
                print(f"{path.name} downloaded (~{size_mb:.1f} MB)")

        print("\nAll location data downloaded successfully!")
        print(f"Files saved in: {data_dir}/")
        return True

    except Exception as e:
        print(f"Error: {e}")
        return False


if __name__ == "__main__":
    download_location_data()
