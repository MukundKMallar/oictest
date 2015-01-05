from oic.oic.message import AtHashError
from oic.oic.message import CHashError

__author__ = 'roland'


MODE = {}

FLOWS = {
    "RP-01": {
        "flow": [("discover", None)],
        "desc": "Can Discover Identifiers using URL Syntax"
    },
    "RP-02": {
        "flow": [("discover", "acct:local@localhost:8080")],
        "desc": "Can Discover Identifiers using acct Syntax"
    },
    "RP-03": {
        "flow": [("discover", None), ("provider_info", None)],
        "desc": "Uses openid-configuration Discovery Information"
    },
    "RP-04": {
        "flow": [("discover", None), ("provider_info", None),
                 ("registration", None)],
        "desc": "Uses Dynamic Registration"
    },
    "RP-05": {
        "flow": [("discover", None), ("provider_info", None),
                 ("registration", None),
                 ("authn_req", {"scope": "openid", "response_type": ["code"]})],
        "desc": "Can Make Request with 'code' Response Type"
    },
    "RP-06": {
        "flow": [("discover", None), ("provider_info", None),
                 ("registration", {"id_token_signed_response_alg": "RS256"}),
                 ("authn_req", {"scope": "openid",
                                "response_type": ["id_token"]})],
        "desc": "Can Make Request with 'id_token' Response Type"
    },
    "RP-07": {
        "flow": [("discover", None), ("provider_info", None),
                 ("registration", {"id_token_signed_response_alg": "RS256"}),
                 ("authn_req", {"scope": "openid",
                                "response_type": ["id_token", "token"]})],
        "desc": "Can Make Request with 'id_token token' Response Type"
    },
    "RP-08": {
        "flow": [("discover", None), ("provider_info", None),
                 ("registration", None),
                 ("authn_req", {"scope": "openid",
                                "response_type": ["code"]}),
                 ("token_req", {"authn_method": "client_secret_basic"})],
        "desc": "Can Make Access Token Request with 'client_secret_basic' "
                "Authentication"
    },
    "RP-09": {
        "flow": [("discover", None), ("provider_info", None),
                 ("registration", None),
                 ("authn_req", {"scope": "openid",
                                "response_type": ["code"]}),
                 ("token_req", {"authn_method": "client_secret_jwt"})],
        "desc": "Can Make Access Token Request with 'client_secret_jwt' "
                "Authentication"
    },
    "RP-10": {
        "flow": [("discover", None), ("provider_info", None),
                 ("registration", None),
                 ("authn_req", {"scope": "openid",
                                "response_type": ["code"]}),
                 ("token_req", {"authn_method": "client_secret_post"})],
        "desc": "Can Make Access Token Request with 'client_secret_post' "
                "Authentication"
    },
    "RP-11": {
        "flow": [("discover", None), ("provider_info", None),
                 ("registration", None),
                 ("authn_req", {"scope": "openid",
                                "response_type": ["code"]}),
                 ("token_req", {"authn_method": "private_key_jwt"})],
        "desc": "Can Make Access Token Request with 'private_key_jwt' "
                "Authentication"
    },
    "RP-12": {
        "flow": [("discover", None), ("provider_info", None),
                 ("registration", {"id_token_signed_response_alg": "RS256"}),
                 ("authn_req", {"scope": "openid",
                                "response_type": ["id_token"]})],
        "desc": "Accept Valid Asymmetric ID Token Signature"
    },
    "RP-13": {
        "flow": [("discover", None), ("provider_info", None),
                 ("registration", {"id_token_signed_response_alg": "HS256"}),
                 ("authn_req", {"scope": "openid",
                                "response_type": ["id_token"]})],
        "desc": "Accept Valid Symmetric ID Token Signature"
    },
    "RP-14": {
        "flow": [("discover", None),
                 ("provider_info", None),
                 ("registration", None),
                 ("authn_req", {"scope": "openid", "response_type": ["code"]}),
                 ("token_req", None),
                 ("userinfo_req", None)],
        "desc": "Can Request and Use JSON UserInfo Response"
    },
    "RP-15": {
        "flow": [("discover", None),
                 ("provider_info", None),
                 ("registration", {"userinfo_signed_response_alg": "RS256"}),
                 ("authn_req", {"scope": "openid", "response_type": ["code"]}),
                 ("token_req", None),
                 ("userinfo_req", None)],
        "desc": "Can Request and Use Signed UserInfo Response"
    },
    #<sign_alg>/<encrypt>/<errtype/<claims>
    "RP-16": {
        "flow": [
            ("discover", None),
            (
                "provider_info",
                {"issuer": "https://localhost:8080/_/_/ath/normal"},
            ),
            (
                "registration",
                {"id_token_signed_response_alg": "RS256"},
            ),
            (
                "authn_req",
                {"scope": "openid", "response_type": ["id_token", "token"]},
                AtHashError
            )],
        "desc": "Rejects incorrect at_hash when Implicit Flow Used"
    },
    "RP-17": {
        "flow": [
            ("discover", None),
            (
                "provider_info",
                {"issuer": "https://localhost:8080/_/_/ch/normal"},
            ),
            (
                "registration",
                {"id_token_signed_response_alg": "RS256"},
            ),
            (
                "authn_req",
                {"scope": "openid", "response_type": ["code", "id_token"]},
                CHashError
            )],
        "desc": "Rejects incorrect at_hash when Implicit Flow Used"
    },
    "RP-18": {
        "flow": [
            ("discover", None),
            ("provider_info", None),
            ("registration", None),
            (
                "authn_req",
                {"scope": "openid", "response_type": ["code"],
                 "claims": {"id_token": {"given_name": {"essential": True}}}},
            ),
            ("token_req", None)],
        "desc": "Can Request and Use Claims in id_token using the 'claims' "
                "request parameter"
    },
}
