"""
Based on https://github.com/jvinet/eip712, adjustments by https://github.com/uxio0

Routines for EIP712 encoding and signing.

Copyright (C) 2022 Judd Vinet <jvinet@zeroflux.org>

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
import re
from typing import Any, Dict, List, Union

from eth_abi import encode_abi
from eth_account import Account
from eth_typing import Hash32, HexStr

from ..utils import fast_keccak


def encode_data(primary_type: str, data, types):
    """
    Encode structured data as per Ethereum's signTypeData_v4.

    https://docs.metamask.io/guide/signing-data.html#sign-typed-data-v4

    This code is ported from the Javascript "eth-sig-util" package.
    """
    encoded_types = ["bytes32"]
    encoded_values = [hash_type(primary_type, types)]

    def _encode_field(name, typ, value):
        if typ in types:
            if value is None:
                return [
                    "bytes32",
                    "0x0000000000000000000000000000000000000000000000000000000000000000",
                ]
            else:
                return ["bytes32", fast_keccak(encode_data(typ, value, types))]

        if value is None:
            raise Exception(f"Missing value for field {name} of type {type}")

        if typ == "bytes":
            return ["bytes32", fast_keccak(value)]

        if typ == "string":
            # Convert string to bytes.
            value = value.encode("utf-8")
            return ["bytes32", fast_keccak(value)]

        if typ.endswith("]"):
            parsed_type = typ[:-2]
            type_value_pairs = dict(
                [_encode_field(name, parsed_type, v) for v in value]
            )
            h = fast_keccak(
                encode_abi(
                    list(type_value_pairs.keys()), list(type_value_pairs.values())
                )
            )
            return ["bytes32", h]

        return [typ, value]

    for field in types[primary_type]:
        typ, val = _encode_field(field["name"], field["type"], data[field["name"]])
        encoded_types.append(typ)
        encoded_values.append(val)

    return encode_abi(encoded_types, encoded_values)


def encode_type(primary_type: str, types) -> str:
    result = ""
    deps = find_type_dependencies(primary_type, types)
    deps = sorted([d for d in deps if d != primary_type])
    deps = [primary_type] + deps
    for typ in deps:
        children = types[typ]
        if not children:
            raise Exception(f"No type definition specified: {type}")

        defs = [f"{t['type']} {t['name']}" for t in types[typ]]
        result += typ + "(" + ",".join(defs) + ")"
    return result


def find_type_dependencies(primary_type: str, types, results=None):
    if results is None:
        results = []

    primary_type = re.split(r"\W", primary_type)[0]
    if primary_type in results or not types.get(primary_type):
        return results
    results.append(primary_type)

    for field in types[primary_type]:
        deps = find_type_dependencies(field["type"], types, results)
        for dep in deps:
            if dep not in results:
                results.append(dep)

    return results


def hash_type(primary_type: str, types) -> Hash32:
    return fast_keccak(encode_type(primary_type, types).encode())


def hash_struct(primary_type: str, data, types) -> Hash32:
    return fast_keccak(encode_data(primary_type, data, types))


def eip712_encode(typed_data: Dict[str, Any]) -> List[bytes]:
    """
    Given a dict of structured data and types, return a 3-element list of
    the encoded, signable data.

      0: The magic & version (0x1901)
      1: The encoded types
      2: The encoded data
    """
    try:
        parts = [
            bytes.fromhex("1901"),
            hash_struct("EIP712Domain", typed_data["domain"], typed_data["types"]),
        ]
        if typed_data["primaryType"] != "EIP712Domain":
            parts.append(
                hash_struct(
                    typed_data["primaryType"],
                    typed_data["message"],
                    typed_data["types"],
                )
            )
        return parts
    except (KeyError, AttributeError, TypeError, IndexError) as exc:
        raise ValueError(f"Not valid {typed_data}") from exc


def eip712_encode_hash(typed_data: Dict[str, Any]) -> Hash32:
    """
    :param typed_data: EIP712 structured data and types
    :return: Keccak256 hash of encoded signable data
    """
    return fast_keccak(b"".join(eip712_encode(typed_data)))


def eip712_signature(
    payload: Dict[str, Any], private_key: Union[HexStr, bytes]
) -> bytes:
    """
    Given a bytes object and a private key, return a signature suitable for
    EIP712 and EIP191 messages.
    """
    if isinstance(payload, (list, tuple)):
        payload = b"".join(payload)

    if isinstance(private_key, str) and private_key.startswith("0x"):
        private_key = private_key[2:]
    elif isinstance(private_key, bytes):
        private_key = bytes.hex()

    account = Account.from_key(private_key)
    hashed_payload = fast_keccak(payload)
    return account.signHash(hashed_payload)["signature"]
