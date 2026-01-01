#!/usr/bin/env python3
"""
r2_hash_token.py - R2トークンValueをSHA-256ハッシュ化

使用方法:
    python r2_hash_token.py
    # または
    uv run python r2_hash_token.py
"""

import getpass
import hashlib


def hash_r2_token():
    """R2トークンValueをSHA-256ハッシュ化して表示"""
    print("R2 Token Value to SHA-256 Hash Converter")
    print("==========================================")
    print()
    print("このスクリプトはCloudflare R2のAPIトークンValueをSHA-256ハッシュ化します。")
    print("ハッシュ化された値を R2_SECRET_ACCESS_KEY として .env に設定してください。")
    print()

    token_value = getpass.getpass("Enter your R2 Token Value: ")

    # SHA-256ハッシュを計算（小文字）
    secret_access_key = hashlib.sha256(token_value.encode("utf-8")).hexdigest()

    print()
    print("Results:")
    print("--------")
    print("Secret Access Key (use this in .env):")
    print(secret_access_key)
    print()
    print("Add to your .env file:")
    print(f"R2_SECRET_ACCESS_KEY={secret_access_key}")
    print()
    print("Note: Token ID (not Value) を R2_ACCESS_KEY_ID に設定してください")


if __name__ == "__main__":
    hash_r2_token()
