import traceback
from collections import OrderedDict
from typing import Optional, Tuple

import pgeocode


class ZipCodeValidator:
    def __init__(self, max_cached_countries: int = 3):
        if max_cached_countries < 1:
            raise ValueError("max_cached_countries must be greater than zero")
        self._nominatim_cache = OrderedDict()
        self._max_cached_countries = max_cached_countries

    def _get_nominatim(self, country_code: str):
        """Get or create Nominatim instance for country"""
        if country_code in self._nominatim_cache:
            self._nominatim_cache.move_to_end(country_code)
            return self._nominatim_cache[country_code]

        try:
            nominatim = pgeocode.Nominatim(country_code)
        except Exception:
            return None

        self._nominatim_cache[country_code] = nominatim
        self._nominatim_cache.move_to_end(country_code)
        while len(self._nominatim_cache) > self._max_cached_countries:
            self._nominatim_cache.popitem(last=False)
        return nominatim

    def validate_zipcode(
        self, zip_code: str, country_code: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate a zip code for a specific country

        Args:
            zip_code: Postal/zip code to validate
            country_code: ISO2 country code (e.g., 'ID', 'US', 'GB')

        Returns:
            Tuple[bool, Optional[str]]: (is_valid, error_message)

        Example:
            >>> validator = ZipCodeValidator()
            >>> is_valid, error = validator.validate_zipcode('12950', 'ID')
            >>> if not is_valid:
            ...     print(error)
        """
        if not zip_code or not country_code:
            return True, None  # Optional field, skip validation if empty

        # Normalize country code
        country_code = country_code.upper()

        # Get Nominatim for country
        nominatim = self._get_nominatim(country_code)
        if nominatim is None:
            # Country not supported by pgeocode, skip validation
            return True, None

        try:
            # Query zip code
            result = nominatim.query_postal_code(zip_code)

            # Check if result is valid
            if result is None or result.empty:
                return (
                    False,
                    f"Zip code '{zip_code}' is not valid for country '{country_code}'",
                )

            # Check if postal_code is NaN (not found)
            if hasattr(result, "postal_code") and str(result.postal_code) == "nan":
                return (
                    False,
                    f"Zip code '{zip_code}' not found for country '{country_code}'",
                )

            return True, None

        except Exception as e:
            # If validation fails, just log and skip validation
            # to avoid blocking user registration
            traceback.print_exc()
            print(f"Warning: Zip code validation failed: {e}")
            return True, None


# Singleton instance
_validator_instance = None


def get_zipcode_validator() -> ZipCodeValidator:
    """Get singleton instance of ZipCodeValidator"""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = ZipCodeValidator()
    return _validator_instance


def validate_zipcode(zip_code: str, country_code: str) -> Tuple[bool, Optional[str]]:
    """
    Helper function to validate zip code

    Args:
        zip_code: Postal/zip code yang akan divalidasi
        country_code: ISO2 country code (e.g., 'ID', 'US', 'GB')

    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
    """
    validator = get_zipcode_validator()
    return validator.validate_zipcode(zip_code, country_code)
