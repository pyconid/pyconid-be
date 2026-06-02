from pathlib import Path
import httpx


def download_location_data():
    base_url = "https://raw.githubusercontent.com/dr5hn/countries-states-cities-database/master/json"
    data_dir = Path("seeders/data/location")
    data_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "countries.json": f"{base_url}/countries.json",
        "states.json": f"{base_url}/states.json",
        "countries+states+cities.json": f"{base_url}/countries+states+cities.json",
    }

    try:
        with httpx.Client(follow_redirects=True, timeout=120) as client:
            for filename, url in files.items():
                path = data_dir / filename
                print(f"Downloading {filename}...")

                with client.stream("GET", url) as r:
                    r.raise_for_status()
                    with open(path, "wb") as f:
                        for chunk in r.iter_bytes():
                            f.write(chunk)

                size_mb = path.stat().st_size / (1024 * 1024)
                print(f"{filename} downloaded (~{size_mb:.1f} MB)")

        print("\nAll location data downloaded successfully!")
        print(f"Files saved in: {data_dir}/")
        return True

    except Exception as e:
        print(f"Error: {e}")
        return False


if __name__ == "__main__":
    download_location_data()
