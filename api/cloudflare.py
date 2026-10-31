"""Cloudflare R2 storage integration module."""

import logging
from threading import Lock
from typing import BinaryIO
from urllib.parse import urlparse
from enum import Enum

import boto3
import botocore.exceptions
from botocore.config import Config
from decouple import config

logger = logging.getLogger(__name__)

_client = None
_client_lock = Lock()


class BucketType(Enum):
    """Enum for supported bucket types."""

    INVOICE = "invoice"
    STATEMENT = "statement"


class R2StorageError(Exception):
    """Custom exception for R2 storage operations."""


def _create_r2_client() -> boto3.client:
    """Create a new R2 client with optimized configuration."""
    try:
        r2_access_key = config("R2_ACCESS_KEY")
        r2_secret_key = config("R2_SECRET_KEY")
        r2_endpoint = config("R2_ENDPOINT")
        r2_region = config("R2_REGION", default="auto")
    except Exception as e:
        raise R2StorageError(
            f"Missing required R2 credentials in environment: {str(e)}"
        ) from e

    boto_config = Config(
        retries={"max_attempts": 3, "mode": "standard"},
        connect_timeout=5,
        read_timeout=30,
        max_pool_connections=10,
    )

    session = boto3.session.Session()
    return session.client(
        "s3",
        aws_access_key_id=r2_access_key,
        aws_secret_access_key=r2_secret_key,
        endpoint_url=r2_endpoint,
        region_name=r2_region,
        config=boto_config,
    )


def get_r2_client() -> boto3.client:
    """
    Get a singleton R2 client instance with thread-safe initialization.

    Returns:
        boto3.client: Configured R2 S3-compatible client

    Raises:
        R2StorageError: If required credentials are missing
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                logger.info("Creating new R2 client singleton")
                _client = _create_r2_client()
    return _client


def reset_r2_client():
    """Reset the R2 client (useful for testing or reconfiguration)."""
    global _client
    with _client_lock:
        _client = None
        logger.info("R2 client reset")


def get_bucket_info(
    bucket_type: BucketType, use_custom_domain: bool = False
) -> tuple[str, str]:
    """
    Get bucket name and domain URL for the specified bucket type.

    Args:
        bucket_type: Type of bucket (BucketType enum)
        use_custom_domain: If True, use custom domain. If False, use R2.dev public domain.

    Returns:
        Tuple of (bucket_name, domain_url)

    Raises:
        R2StorageError: If required environment variables are missing
    """
    # Keep the bucket type value as-is for the bucket name (e.g., "invoice" not "INVOICE")
    # But use uppercase for environment variable names
    bucket_type_value = bucket_type.value  # "invoice" or "statement"
    bucket_type_upper = bucket_type_value.upper()  # "INVOICE" or "STATEMENT"

    bucket_env = f"R2_{bucket_type_upper}_BUCKET"

    try:
        bucket_name = config(bucket_env)
    except Exception as exc:
        raise R2StorageError(f"Missing environment variable: {bucket_env}") from exc

    if use_custom_domain:
        domain_env = f"{bucket_type_upper}_DOMAIN"
        try:
            domain_url = config(domain_env)
        except Exception as exc:
            raise R2StorageError(f"Missing environment variable: {domain_env}") from exc
    else:
        # Use Cloudflare R2.dev public domain
        r2_dev_url_env = f"R2_{bucket_type_upper}_PUBLIC_URL"
        try:
            domain_url = config(r2_dev_url_env)
        except Exception as exc:
            raise R2StorageError(
                f"Missing environment variable: {r2_dev_url_env}. "
                f"This should be your R2 bucket's public URL (e.g., https://pub-xxxxx.r2.dev)"
            ) from exc

    return bucket_name, domain_url


def extract_filename_from_url(file_url: str) -> str:
    """
    Extract filename from URL safely.

    Args:
        file_url: Full URL of the file

    Returns:
        Extracted filename

    Raises:
        ValueError: If URL is invalid or filename cannot be extracted
    """
    if not file_url:
        raise ValueError("file_url cannot be empty")

    try:
        parsed = urlparse(file_url)
        filename = parsed.path.rstrip("/").split("/")[-1]

        if not filename:
            raise ValueError(f"Could not extract filename from URL: {file_url}")

        return filename
    except Exception as e:
        raise ValueError(f"Invalid URL format: {file_url}") from e


def delete_from_r2(
    file_url: str,
    bucket_type: BucketType = BucketType.INVOICE,
    use_custom_domain: bool = False,
) -> bool:
    """
    Delete a file from R2 storage.

    Args:
        file_url: The URL of the file to delete
        bucket_type: Type of bucket (defaults to INVOICE)
        use_custom_domain: Whether the URL uses custom domain (defaults to False)

    Returns:
        True if deletion was successful or file doesn't exist, False on error
    """
    try:
        client = get_r2_client()
        bucket_name, _ = get_bucket_info(bucket_type, use_custom_domain)
        filename = extract_filename_from_url(file_url)

        client.delete_object(Bucket=bucket_name, Key=filename)
        logger.debug(
            "Successfully deleted file '%s' from '%s' bucket",
            filename,
            bucket_type.value,
        )
        return True

    except botocore.exceptions.ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")

        if error_code in ["404", "NoSuchKey"]:
            logger.warning(
                "File '%s' not found in '%s' bucket "
                "(already deleted or never existed)",
                filename,
                bucket_type.value,
            )
            return True

        logger.error(
            "AWS error deleting file '%s' from '%s': %s - %s",
            filename,
            bucket_type.value,
            error_code,
            str(e),
        )
        return False

    except R2StorageError as e:
        logger.error("R2 configuration error: %s", str(e))
        return False

    except (ValueError, botocore.exceptions.BotoCoreError) as e:
        logger.error(
            "Unexpected error deleting file from '%s' bucket: %s: %s",
            bucket_type.value,
            type(e).__name__,
            str(e),
        )
        return False


def upload_pdf_to_r2(
    file_obj: BinaryIO,
    filename: str,
    bucket_type: BucketType = BucketType.INVOICE,
    make_public: bool = True,
    use_custom_domain: bool = False,
) -> str:
    """
    Upload a PDF file to R2 storage.

    Args:
        file_obj: File-like object to upload (must be open for reading in binary mode)
        filename: Name to save the file as in R2
        bucket_type: Type of bucket (defaults to INVOICE)
        make_public: Whether to make the file publicly readable
        use_custom_domain: If True, return custom domain URL. If False, return R2 public URL.

    Returns:
        str: Public URL of the uploaded file.

    Raises:
        R2StorageError: If upload fails
        ValueError: If filename is invalid
    """
    if not filename:
        raise ValueError("filename cannot be empty")

    if not filename.lower().endswith(".pdf"):
        logger.warning("Filename '%s' doesn't end with .pdf", filename)

    try:
        client = get_r2_client()
        bucket_name, domain_url = get_bucket_info(bucket_type, use_custom_domain)

        if hasattr(file_obj, "seek"):
            file_obj.seek(0)

        extra_args = {"ContentType": "application/pdf"}

        client.upload_fileobj(
            Fileobj=file_obj,
            Bucket=bucket_name,
            Key=filename,
            ExtraArgs=extra_args,
        )

        file_url = f"{domain_url.rstrip('/')}/{filename}"
        logger.debug(
            "Successfully uploaded '%s' to '%s' bucket",
            filename,
            bucket_type.value,
        )
        return file_url

    except botocore.exceptions.ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        error_msg = f"AWS error uploading '{filename}': {error_code} - {str(e)}"
        logger.error(error_msg)
        raise R2StorageError(error_msg) from e

    except R2StorageError:
        raise

    except Exception as e:
        error_msg = (
            f"Unexpected error uploading '{filename}' to '{bucket_type.value}': "
            f"{type(e).__name__}: {str(e)}"
        )
        logger.error(error_msg)
        raise R2StorageError(error_msg) from e


def check_file_exists(
    file_url: str,
    bucket_type: BucketType = BucketType.INVOICE,
    use_custom_domain: bool = False,
) -> bool:
    """
    Check if a file exists in R2 storage.

    Args:
        file_url: The URL of the file to check
        bucket_type: Type of bucket (defaults to INVOICE)
        use_custom_domain: Whether the URL uses custom domain (defaults to False)

    Returns:
        True if file exists, False otherwise
    """
    if not file_url:
        return False

    try:
        client = get_r2_client()
        bucket_name, _ = get_bucket_info(bucket_type, use_custom_domain)
        filename = extract_filename_from_url(file_url)

        client.head_object(Bucket=bucket_name, Key=filename)
        logger.debug("File '%s' exists in '%s' bucket", filename, bucket_type.value)
        return True

    except botocore.exceptions.ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")

        if error_code in ["404", "NoSuchKey"]:
            logger.debug(
                "File '%s' not found in '%s' bucket", filename, bucket_type.value
            )
            return False

        logger.error(
            "Error checking file '%s' in '%s': %s - %s",
            filename,
            bucket_type.value,
            error_code,
            str(e),
        )
        return False

    except R2StorageError as e:
        logger.error("R2 configuration error: %s", str(e))
        return False

    except (ValueError, botocore.exceptions.BotoCoreError) as e:
        logger.error(
            "Unexpected error checking file existence: %s: %s",
            type(e).__name__,
            str(e),
        )
        return False


def get_file_metadata(
    file_url: str,
    bucket_type: BucketType = BucketType.INVOICE,
    use_custom_domain: bool = False,
) -> dict:
    """
    Get metadata for a file in R2 storage.

    Args:
        file_url: The URL of the file
        bucket_type: Type of bucket (defaults to INVOICE)
        use_custom_domain: Whether the URL uses custom domain (defaults to False)

    Returns:
        Dictionary containing file metadata (size, content-type, etc.)
        Empty dict if file doesn't exist or error occurs
    """
    try:
        client = get_r2_client()
        bucket_name, _ = get_bucket_info(bucket_type, use_custom_domain)
        filename = extract_filename_from_url(file_url)

        response = client.head_object(Bucket=bucket_name, Key=filename)

        metadata = {
            "content_length": response.get("ContentLength", 0),
            "content_type": response.get("ContentType", ""),
            "last_modified": response.get("LastModified"),
            "etag": response.get("ETag", "").strip('"'),
        }

        logger.debug("Retrieved metadata for '%s'", filename)
        return metadata

    except botocore.exceptions.ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in ["404", "NoSuchKey"]:
            logger.warning("File '%s' not found", filename)
        else:
            logger.error("Error getting metadata: %s", str(e))
        return {}

    except (ValueError, botocore.exceptions.BotoCoreError) as e:
        logger.error("Unexpected error getting metadata: %s", str(e))
        return {}
