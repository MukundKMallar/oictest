#!/usr/bin/env python
import copy
from jwkest.jwk import SerializationNotPossible
from oic.exception import UnSupported
from oic.utils.keyio import KeyBundle
from oic.utils.keyio import dump_jwks
from oic.oauth2.message import SchemeError
from oic.utils.webfinger import OIC_ISSUER, WebFinger
from oic.utils.http_util import Response

import rrtest.request as req
from rrtest.request import BodyResponse
from rrtest.request import GetRequest
from rrtest.request import Request
from rrtest.request import UrlResponse
from rrtest.request import PostRequest
from rrtest.request import Process
from rrtest.check import VerifyBadRequestResponse
from rrtest.check import CheckErrorResponse

__author__ = 'rohe0002'

# ========================================================================

import time

from urllib import urlencode
from oic.oauth2 import JSON_ENCODED
from oic.oauth2 import PBase

# Used upstream not in this module so don't remove
from oictest.check import *
from rrtest.opfunc import *

# ========================================================================

LOCAL_PATH = "export/"


class MissingResponseClaim(Exception):
    pass


class NotSupported(Exception):
    pass


class RequirementsNotMet(Exception):
    pass


def get_base(cconf=None):
    """
    Make sure a '/' terminated URL is returned
    """
    try:
        part = urlparse(cconf["_base_url"])
    except KeyError:
        part = urlparse(cconf["base_url"])
    # part = urlparse(cconf["redirect_uris"][0])

    if part.path:
        if not part.path.endswith("/"):
            _path = part.path[:] + "/"
        else:
            _path = part.path[:]
    else:
        _path = "/"

    return "%s://%s%s" % (part.scheme, part.netloc, _path, )


# noinspection PyUnusedLocal


def store_sector_redirect_uris(args, alla=True, extra=False, cconf=None):
    _base = get_base(cconf)

    sector_identifier_url = "%s%s%s" % (_base, LOCAL_PATH, "siu.json")
    f = open("%ssiu.json" % LOCAL_PATH, 'w')
    if all:
        f.write(json.dumps(args["redirect_uris"]))
    else:
        f.write(json.dumps(args["redirect_uris"][:-1]))
    f.close()

    if extra:
        args["redirect_uris"].append("%scb" % _base)

    args["sector_identifier_uri"] = sector_identifier_url


def response_claim(conv, respcls, claim):
    for (instance, msg) in conv.protocol_response:
        if isinstance(instance, respcls):
            return instance[claim]

    return None


# -----------------------------------------------------------------------------


class TimeDelay(Process):
    def __init__(self):
        self.delay = 2
        self.tests = {"post": [], "pre": []}

    def __call__(self, *args, **kwargs):
        time.sleep(self.delay)
        return None


class Notice(Process):
    def __init__(self):
        self.tests = {"post": [], "pre": []}
        self.template = ""

    def __call__(self, lookup, environ, start_response, **kwargs):
        resp = Response(mako_template=self.template,
                        template_lookup=lookup,
                        headers=[])
        return resp(environ, start_response, **kwargs)

    def cache(self, cache, conv, items):
        return None


class ExpectError(Notice):
    def __init__(self):
        Notice.__init__(self)
        self.template = "expect_err.mako"


class RmCookie(Notice):
    def __init__(self):
        Notice.__init__(self)
        self.template = "rmcookie.mako"

    def cache(self, cache, conv, items):
        pack = {}
        for item in items:
            if item == "id_token":
                pack[item] = conv.id_token

        key = hash("%s%f" % (items, time.time()))
        cache[str(key)] = pack
        return key


class Note(Notice):
    def __init__(self):
        Notice.__init__(self)
        self.template = "note.mako"


class DisplayUserInfo(Notice):
    def __init__(self):
        Notice.__init__(self)
        self.template = "userinfo.mako"


class DisplayIDToken(Notice):
    def __init__(self):
        Notice.__init__(self)
        self.template = "idtoken.mako"


class RotateKeys(Process):
    def __init__(self):
        self.jwk_name = "export/jwk.json"
        self.tests = {"post": [], "pre": []}
        self.new_key = {}
        self.kid_template = "_%d"
        self.key_usage = ""

    def __call__(self, conv, **kwargs):
        # find the name of the file to which the JWKS should be written
        try:
            _uri = conv.client.registration_response["jwks_uri"]
        except KeyError:
            raise RequirementsNotMet("No dynamic key handling")

        r = urlparse(_uri)
        # find the old key for this key usage and mark that as inactive
        for kb in conv.client.keyjar.issuer_keys[""]:
            for key in kb.keys():
                if key.use in self.new_key["use"]:
                    key.inactive = True

        kid = 0
        # only one key
        _nk = self.new_key
        _typ = _nk["type"].upper()

        if _typ == "RSA":
            kb = KeyBundle(source="file://%s" % _nk["key"],
                           fileformat="der", keytype=_typ,
                           keyusage=_nk["use"])
        else:
            kb = {}

        for k in kb.keys():
            k.serialize()
            k.kid = self.kid_template % kid
            kid += 1
            conv.client.kid[k.use][k.kty] = k.kid
        conv.client.keyjar.add_kb("", kb)

        dump_jwks(conv.client.keyjar[""], r.path[1:])


class RotateSigKeys(RotateKeys):
    def __init__(self):
        RotateKeys.__init__(self)
        self.new_key = {"type": "RSA", "key": "../keys/second_sig.key",
                        "use": ["sig"]}
        self.kid_template = "sig%d"


class RotateEncKeys(RotateKeys):
    def __init__(self):
        RotateKeys.__init__(self)
        self.new_key = {"type": "RSA", "key": "../keys/second_enc.key",
                        "use": ["enc"]}
        self.kid_template = "enc%d"


# -----------------------------------------------------------------------------


class ProviderRequest(GetRequest):
    request = ""
    _tests = {"pre": [], "post": []}

    def __call__(self, *args, **kwargs):
        if "endpoint" in kwargs:
            kwargs["endpoint"] += ".well-known/openid-configuration"

        url, response, text = GetRequest.__call__(self, *args, **kwargs)
        return url, response, text


class MissingResponseType(GetRequest):
    request = "AuthorizationRequest"
    _request_args = {"response_type": [], "scope": ["openid"]}
    lax = True
    _tests = {"post": [CheckErrorResponse]}


class AuthorizationRequest(GetRequest):
    request = "AuthorizationRequest"
    _request_args = {"scope": ["openid"]}
    _tests = {"pre": [CheckResponseType, CheckEndpoint],
              "post": []}
    interaction_check = True


class AuthorizationRequestCode(AuthorizationRequest):
    request = "AuthorizationRequest"
    _request_args = {"response_type": ["code"], "scope": ["openid"]}


class AuthorizationRequestToken(AuthorizationRequest):
    request = "AuthorizationRequest"
    _request_args = {"response_type": ["token"], "scope": ["openid"]}


class AuthorizationRequestIDToken(AuthorizationRequest):
    request = "AuthorizationRequest"
    _request_args = {"response_type": ["id_token"], "scope": ["openid"]}
    _tests = {"pre": [CheckResponseType, CheckScopeSupport, CheckEndpoint],
              "post": []}


class AuthorizationRequestCodeUri(AuthorizationRequestCode):
    pass
    # def __init__(self, conv=None):
    # AuthorizationRequestCode.__init__(self, conv)
    # self.tests["post"].extend([VerifyPolicyURLs, VerifyLogoURLs])


class AuthorizationRequestCode_WQC(AuthorizationRequestCode):
    def __init__(self, conv=None):
        AuthorizationRequestCode.__init__(self, conv)
        self.set_request_args({"query": "component"})


class AuthorizationRequestCode_RUWQC(AuthorizationRequestCode):
    def __call__(self, location, response="", content="", features=None,
                 **kwargs):
        _client = self.conv.client
        base_url = _client.redirect_uris[0]
        self.request_args["redirect_uri"] = "%s?%s" % (
            base_url, urlencode({"fox": "bat"}))
        return Request.__call__(self, location, response, content, features,
                                **kwargs)


class AuthorizationRequestCode_RUWQC_Err(AuthorizationRequestCode_RUWQC):
    def __init__(self, conv):
        AuthorizationRequestCode_RUWQC.__init__(self, conv)
        self.tests["post"] = [CheckErrorResponse]


class AuthorizationRequestMismatchingRedirectURI(AuthorizationRequestCode):
    def __init__(self, conv=None):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["redirect_uri"] = "https://foo.example.se/authz_cb"
        self.tests["post"] = [CheckErrorResponse]


class AuthorizationRequestNoRedirectURI(AuthorizationRequestCode):
    def __init__(self, conv=None):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["redirect_uri"] = ""
        self.tests["post"] = [VerifyBadRequestResponse]


class AuthorizationRequestCodeWithNonce(AuthorizationRequestCode):
    def __init__(self, conv=None):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["nonce"] = "12nonce34"


class AuthorizationRequestCodeWithoutNonce(AuthorizationRequestCode):
    # return_type = "code", nonce not required
    def __init__(self, conv=None):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["nonce"] = ""


class AuthorizationRequestWithoutNonce(AuthorizationRequestIDToken):
    # return_type = "id_token", nonce required
    def __init__(self, conv=None):
        AuthorizationRequestIDToken.__init__(self, conv)
        self.request_args["nonce"] = ""
        self.tests["post"] = [CheckErrorResponse]


class AuthorizationRequestCodeRequestInFile(AuthorizationRequestCode):
    _kw_args = {"request_method": "file", "local_dir": "export"}

    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.kw_args["base_path"] = get_base(conv.client_config) + "export/"
        self.tests["pre"].append(CheckRequestURIParameterSupported)


class AuthorizationRequestCodeRequestParameter(AuthorizationRequestCode):
    _kw_args = {"request_method": "parameter"}

    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.tests["pre"].append(CheckRequestParameterSupported)
        self.tests["pre"].append(CheckRequestClaimsSupport)


class ConnectionVerify(GetRequest):
    request = "AuthorizationRequest"
    _request_args = {"response_type": ["code"], "scope": ["openid"]}
    _tests = {"pre": [CheckResponseType, CheckEndpoint],
              "post": []}
    interaction_check = True


class AuthorizationRequestCodeDisplayPage(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["display"] = "page"


class AuthorizationRequestCodeDisplayPopUp(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["display"] = "popup"


class AuthorizationRequestCodePromptNone(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["prompt"] = "none"
        # self.tests["post"] = [VerifyErrorResponse]


class AuthorizationRequestCodePromptNoneWithIdToken(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["prompt"] = "none"

    def call_setup(self):
        try:
            idt = self.conv.id_token
        except AttributeError:
            _key = self.conv.cache_key
            idt = self.conv.cache[_key]["id_token"]

        # If it's encrypted should re-encrypt
        self.request_args["id_token"] = idt

    def __call__(self, location, response="", content="", features=None,
                 **kwargs):
        return AuthorizationRequestCode.__call__(self, location, response,
                                                 content, features, **kwargs)


class AuthorizationRequestCodeWithSubClaim(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)

    def call_setup(self):
        idt = response_claim(self.conv, message.AccessTokenResponse, "id_token")
        if not idt:
            try:
                _key = self.conv.cache_key
                idt = self.conv.cache[_key]["id_token"]
            except (AttributeError, KeyError):
                raise MissingResponseClaim("id_token in access token response")

        _sub = idt["sub"]
        self.request_args["claims"] = {"id_token": {"sub": {"value": _sub}}}

    def __call__(self, location, response="", content="", features=None,
                 **kwargs):
        return AuthorizationRequestCode.__call__(self, location, response,
                                                 content, features, **kwargs)


class AuthorizationRequestCodePromptNoneWithSubClaim(
    AuthorizationRequestCodeWithSubClaim):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["prompt"] = "none"
        self.tests["post"] = [VerifyPromptNoneResponse]


class AuthorizationRequestCodePromptLogin(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["prompt"] = "login"


class AuthorizationRequestCodeScopeProfile(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["scope"].append("profile")
        self.set_request_args({"scope": self.request_args["scope"]})
        self.tests["pre"].append(CheckScopeSupport)


class AuthorizationRequestCodeScopeEMail(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["scope"].append("email")
        self.set_request_args({"scope": self.request_args["scope"]})
        self.tests["pre"].append(CheckScopeSupport)


class AuthorizationRequestCodeScopeAddress(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["scope"].append("address")
        self.set_request_args({"scope": self.request_args["scope"]})
        self.tests["pre"].append(CheckScopeSupport)


class AuthorizationRequestCodeScopePhone(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["scope"].append("phone")
        self.set_request_args({"scope": self.request_args["scope"]})
        self.tests["pre"].append(CheckScopeSupport)


class AuthorizationRequestCodeScopeOfflineAccess(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["scope"].append("offline_access")
        self.set_request_args({
            "scope": self.request_args["scope"],
            "prompt": "consent"})
        self.tests["pre"].append(CheckScopeSupport)


class AuthorizationRequestCodeScopeAll(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["scope"].extend(["phone", "address", "email",
                                           "profile"])
        self.set_request_args({"scope": self.request_args["scope"]})
        self.tests["pre"].append(CheckScopeSupport)


class AuthorizationRequestCodeUIClaim1(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["claims"] = {
            "userinfo": {"name": {"essential": True}}}
        self.tests["pre"].append(CheckRequestParameterSupported)
        self.tests["pre"].append(CheckRequestClaimsSupport)


class AuthorizationRequestCodeUIClaim1RequestParam(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["request"] = "request"
        self.request_args["claims"] = {
            "userinfo": {"name": {"essential": True}}}
        self.tests["pre"].append(CheckRequestParameterSupported)
        self.tests["pre"].append(CheckRequestClaimsSupport)


class AuthorizationRequestCodeUIClaim1RequestURI(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["request"] = "request_uri"
        self.request_args["claims"] = {
            "userinfo": {"name": {"essential": True}}}
        self.tests["pre"].append(CheckRequestParameterSupported)
        self.tests["pre"].append(CheckRequestClaimsSupport)


class AuthorizationRequestCodeUIClaim2(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        # Picture and email optional
        self.request_args["claims"] = {
            "userinfo": {"picture": None, "email": None}}
        self.tests["pre"].append(CheckClaimsSupport)


class AuthorizationRequestCodeUIClaim3(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        # Must name, may picture and email
        self.request_args["claims"] = {
            "userinfo": {"name": {"essential": True},
                         "picture": None,
                         "email": None}}
        self.tests["pre"].append(CheckClaimsSupport)


class AuthorizationRequestCodeUICombiningClaims(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        # Must name, may picture and email
        self.request_args["scope"].append("address")
        self.set_request_args({
            "scope": self.request_args["scope"],
            "claims": {
                "userinfo": {"name": {"essential": True},
                             "picture": None,
                             "email": None}}})
        self.tests["pre"].append(CheckClaimsSupport)


class AuthorizationRequestCodeIDTClaim1(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        # Must auth_time
        self.request_args["claims"] = {
            "id_token": {"auth_time": {"essential": True}}}
        self.tests["pre"].append(CheckClaimsSupport)


class AuthorizationRequestCodeIDTClaim2(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        try:
            _acrs = conv.client_config["acr_values"]
        except KeyError:
            _acrs = ["2"]

        self.request_args["claims"] = {"id_token": {"acr": {"values": _acrs}}}
        self.tests["pre"].append(CheckAcrSupport)


class AuthorizationRequestCodeIDTClaim3(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        # Must acr
        self.request_args["claims"] = {"id_token": {"acr": {"essential": True}}}


class AuthorizationRequestCodeIDTClaim4(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        # Must acr
        self.request_args["claims"] = {"id_token": {"acr": None}}


class AuthorizationRequestCodeIDTClaimX(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        # Must acr
        self.request_args["claims"] = {
            "id_token": {"auth_time": {"essential": True}}}


class AuthorizationRequestCodeIDTMaxAge1(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.set_request_args({"max_age": 1})


class AuthorizationRequestCodeIDTMaxAge1000(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.set_request_args({"max_age": 1000})


class AuthorizationRequestUILocale(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        # Just so something can be seen
        self.request_args["scope"].extend(["phone", "address", "email",
                                           "profile"])
        self.set_request_args({"scope": self.request_args["scope"]})
        try:
            uil = conv.client_config["ui_locales"]
        except KeyError:
            try:
                uil = conv.client_config["locales"]
            except KeyError:
                uil = ["se"]

        self.set_request_args({"ui_locales": uil})


class AuthorizationRequestClaimsLocale(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        try:
            loc = conv.client_config["claims_locale"]
        except KeyError:
            try:
                loc = conv.client_config["locales"]
            except KeyError:
                loc = ["se"]
        self.set_request_args({"claims_locale": loc})


class AuthorizationRequestLoginHint(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        try:
            hint = conv.client_config["login_hint"]
        except KeyError:
            hint = "foo@bar.com"
        self.set_request_args({"login-hint": "%s" % hint})


class AuthorizationRequestAcrValues(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.set_request_args({"acr_values": ["1"]})


class AuthorizationRequestCodeIDTEmail(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["claims"] = {
            "id_token": {"email": {"essential": True}}}


class AuthorizationRequestCodeMixedClaims(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.request_args["claims"] = {
            "id_token": {"email": {"essential": True}},
            "userinfo": {"name": {"essential": True}}}


class AuthorizationRequestCodeToken(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.set_request_args({"response_type": ["code", "token"]})


class AuthorizationRequestCodeIDToken(AuthorizationRequestCode):
    def __init__(self, conv):
        AuthorizationRequestCode.__init__(self, conv)
        self.set_request_args({"response_type": ["code", "id_token"]})


class AuthorizationRequestIDTokenToken(AuthorizationRequestIDToken):
    def __init__(self, conv):
        AuthorizationRequestIDToken.__init__(self, conv)
        self.set_request_args({"response_type": ["id_token", "token"]})


class AuthorizationRequestCodeIDTokenToken(AuthorizationRequestCodeIDToken):
    def __init__(self, conv):
        AuthorizationRequestCodeIDToken.__init__(self, conv)
        self.set_request_args({"response_type": ["code", "id_token", "token"]})


class AuthorizationRequestCodeResponseModeFormPost(AuthorizationRequestCode):
    def __init__(self, conv=None):
        AuthorizationRequestCode.__init__(self, conv)
        self.set_request_args({"response_mode": "form_post"})


# =============================================================================


class RegistrationRequest(PostRequest):
    request = "RegistrationRequest"
    content_type = JSON_ENCODED
    _request_args = {}

    def __init__(self, conv):
        PostRequest.__init__(self, conv)

        for arg in message.RegistrationRequest().parameters():
            try:
                val = conv.client_config["provider_info"][arg]
            except KeyError:
                try:
                    val = conv.client_config["preferences"][arg]
                except KeyError:
                    try:
                        val = conv.client_config["client_info"][arg]
                    except KeyError:
                        try:
                            val = conv.client_config["client_registration"][arg]
                        except KeyError:
                            continue
            self.request_args[arg] = copy.copy(val)
        try:
            del self.request_args["key_export_url"]
        except KeyError:
            pass

        # verify the registration info
        self.tests["post"].append(RegistrationInfo)
        # try:
        # self.tests["pre"].append(VerifyOPHasRegistrationEndpoint)
        # except KeyError:
        # self.tests["pre"] = [VerifyOPHasRegistrationEndpoint]


class BasicRegistrationRequest(RegistrationRequest):
    def __call__(self, location, response="", content="", features=None,
                 **kwargs):
        _client = self.conv.client
        # The only required parameter
        self.request_args = {
            "redirect_uris": _client.redirect_uris,
            "response_types": ["code"],
            # "grant_types": ["authorization_code", "implicit"] - default
        }

        return RegistrationRequest.__call__(self, location, response, content,
                                            features, **kwargs)


class ImplicitRegistrationRequest(RegistrationRequest):
    def __call__(self, location, response="", content="", features=None,
                 **kwargs):
        _client = self.conv.client
        # The only required parameter
        self.request_args = {
            "redirect_uris": _client.redirect_uris,
            "response_types": ["id_token", "id_token token"],
        }

        return RegistrationRequest.__call__(self, location, response, content,
                                            features, **kwargs)


class HybridRegistrationRequest(RegistrationRequest):
    def __call__(self, location, response="", content="", features=None,
                 **kwargs):
        _client = self.conv.client
        # The only required parameter
        self.request_args = {
            "redirect_uris": _client.redirect_uris,
            "response_types": ["code id_token", "code token",
                               "code id_token token"],
        }

        return RegistrationRequest.__call__(self, location, response, content,
                                            features, **kwargs)

class RegistrationRequestMULREDIR(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        self.request_args["redirect_uris"].append(
            "%scb" % get_base(conv.client_config))


class RegistrationRequestMULREDIRMultHost(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        self.request_args["redirect_uris"].append("https://example.org/cb")


class RegistrationRequestHTTPREDIR(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        base_url = self.conv.client.redirect_uris[0].replace("https", "http")
        self.request_args["redirect_uris"] = [base_url]


class RegistrationRequest_WQC(RegistrationRequest):
    """ With query component """

    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)

        ru = self.request_args["redirect_uris"][0]
        if "?" in ru:
            ru += "&foo=bar"
        else:
            ru += "?foo=bar"
        self.request_args["redirect_uris"][0] = ru


class RegistrationRequest_WF(RegistrationRequest):
    """ With fragment, which is not allowed """
    _tests = {"post": [CheckErrorResponse]}

    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)

        ru = self.request_args["redirect_uris"][0]
        ru += "#fragment"
        self.request_args["redirect_uris"][0] = ru


class RegistrationRequest_KeyExpCSJ(RegistrationRequest):
    """ Registration request with client key export """
    request = "RegistrationRequest"

    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        self.set_request_args({
            "token_endpoint_auth_method": "client_secret_jwt"})
        self.tests["pre"].append(CheckTokenEndpointAuthMethod)
        # self.export_server = "http://%s:8090/export" % socket.gethostname()

    def __call__(self, location, response="", content="", features=None,
                 **kwargs):
        _client = self.conv.client
        # Do the redirect_uris dynamically
        self.request_args["redirect_uris"] = _client.redirect_uris

        return PostRequest.__call__(self, location, response,
                                    content, features, **kwargs)


class RegistrationRequest_KeyExpCSP(RegistrationRequest):
    """ Registration request with client key export """
    request = "RegistrationRequest"

    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        self.set_request_args({
            "token_endpoint_auth_method": "client_secret_post"})
        self.tests["pre"].append(CheckTokenEndpointAuthMethod)
        # self.export_server = "http://%s:8090/export" % socket.gethostname()

    def __call__(self, location, response="", content="", features=None,
                 **kwargs):
        _client = self.conv.client
        # Do the redirect_uris dynamically
        self.request_args["redirect_uris"] = _client.redirect_uris

        return PostRequest.__call__(self, location, response,
                                    content, features, **kwargs)


class RegistrationRequest_KeyExpPKJ(RegistrationRequest):
    """ Registration request with client key export """
    request = "RegistrationRequest"

    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        self.set_request_args({"token_endpoint_auth_method": "private_key_jwt"})
        self.tests["pre"].append(CheckTokenEndpointAuthMethod)
        # self.export_server = "http://%s:8090/export" % socket.gethostname()

    def __call__(self, location, response="", content="", features=None,
                 **kwargs):
        _client = self.conv.client
        # Do the redirect_uris dynamically
        self.request_args["redirect_uris"] = _client.redirect_uris

        return PostRequest.__call__(self, location, response,
                                    content, features, **kwargs)


class RegistrationRequestPolicyLogoTos(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)

        ruri = self.request_args["redirect_uris"][0]
        p = urlparse(ruri)

        self.request_args["policy_uri"] = "%s://%s/%s" % (p.scheme, p.netloc,
                                                          "static/policy.html")
        self.request_args["logo_uri"] = "%s://%s/%s" % (p.scheme, p.netloc,
                                                        "static/logo.png")
        self.request_args["tos_uri"] = "%s://%s/%s" % (p.scheme, p.netloc,
                                                       "static/tos.html")


class RegistrationRequest_with_public_userid(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        self.set_request_args({"subject_type": "public"})
        self.tests["pre"].append(CheckUserIdSupport)


class RegistrationRequest_with_userinfo_signed(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        self.set_request_args({"userinfo_signed_response_alg": "RS256"})
        self.tests["pre"].append(CheckSignedUserInfoSupport)


class RegistrationRequest_with_pairwise_userid(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        self.set_request_args({"subject_type": "pairwise"})
        self.tests["pre"].append(CheckUserIdSupport)
        store_sector_redirect_uris(self.request_args, cconf=conv.client_config)


class RegistrationRequest_with_id_token_signed_response_alg(
    RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        self.set_request_args({"id_token_signed_response_alg": "HS256"})
        self.tests["pre"].append(CheckSignedIdTokenSupport)


class RegistrationRequestWithUnSignedIDToken(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        self.set_request_args({"id_token_signed_response_alg": "none"})
        self.tests["pre"].append(CheckSignedIdTokenSupport)


class RegistrationRequest_SectorID(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        store_sector_redirect_uris(self.request_args, cconf=conv.client_config)


class RegistrationRequest_SectorID_2(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        _base = get_base(conv.client_config)
        self.request_args["redirect_uris"].append("%scb" % _base)
        store_sector_redirect_uris(self.request_args, cconf=conv.client_config)


class RegistrationRequest_SectorID_Err(RegistrationRequest):
    """Sector Identifier Not Containing Registered redirect_uri Values"""

    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        store_sector_redirect_uris(self.request_args, False, True,
                                   cconf=conv.client_config)
        # self.request_args["redirect_uris"].append("%scb" % get_base(cconf))
        self.tests["post"] = [CheckErrorResponse]


class RegistrationRequestEncUserinfo(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        self.set_request_args({
            "userinfo_signed_response_alg": "none",
            "userinfo_encrypted_response_alg": "RSA1_5",
            "userinfo_encrypted_response_enc": "A128CBC-HS256"})
        self.tests["pre"].extend([CheckEncryptedUserInfoSupportALG,
                                  CheckEncryptedUserInfoSupportENC])


class RegistrationRequestSignEncUserinfo(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        self.set_request_args({
            "userinfo_signed_response_alg": "RS256",
            "userinfo_encrypted_response_alg": "RSA1_5",
            "userinfo_encrypted_response_enc": "A128CBC-HS256"})
        self.tests["pre"].extend([CheckEncryptedUserInfoSupportALG,
                                  CheckEncryptedUserInfoSupportENC])


class RegistrationRequestESSigIDtoken(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        self.set_request_args({"id_token_signed_response_alg": "ES256"})
        self.tests["pre"].extend([CheckSignedRequestObjectSupport])


class RegistrationRequestEncIDtoken(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        self.set_request_args({
            "id_token_signed_response_alg": "none",
            "id_token_encrypted_response_alg": "RSA1_5",
            "id_token_encrypted_response_enc": "A128CBC-HS256"})
        self.tests["pre"].extend([CheckEncryptedIDTokenSupportALG,
                                  CheckEncryptedIDTokenSupportENC])


class RegistrationRequestSignEncIDtoken(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        self.set_request_args({
            "id_token_signed_response_alg": "RS256",
            "id_token_encrypted_response_alg": "RSA1_5",
            "id_token_encrypted_response_enc": "A128CBC-HS256"})

        self.tests["pre"].extend([CheckEncryptedIDTokenSupportALG,
                                  CheckEncryptedIDTokenSupportENC])


class RegistrationRequestJWKS(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        _client = self.conv.client
        self.request_args["jwks_uri"] = None
        self.request_args["jwks"] = {
            "keys": _client.keyjar.dump_issuer_keys("")}


class RegistrationRequestNoResponseTypes(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        del conv.client.behaviour["response_types"]
        # self.request_args["response_types"] = None


class RegistrationRequestResponseTypesToken(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        self.set_request_args({"response_types": ["token"]})


class RegistrationRequestNoneSig(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        self.set_request_args({"request_object_signing_alg": "none"})
        self.tests["pre"].extend([CheckSignedRequestObjectSupport])


class RegistrationRequestSig(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        self.set_request_args({"request_object_signing_alg": "RS256"})
        self.tests["pre"].extend([CheckSignedRequestObjectSupport])


class RegistrationRequestEnc(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        self.set_request_args({
            "request_object_signing_alg": "none",
            "request_object_encryption_alg": "RSA1_5",
            "request_object_encryption_enc": "A128CBC-HS256"})
        self.tests["pre"].extend([CheckEncryptedRequestObjectSupportALG,
                                  CheckEncryptedRequestObjectSupportENC])


class RegistrationRequestSigEnc(RegistrationRequest):
    def __init__(self, conv):
        RegistrationRequest.__init__(self, conv)
        self.set_request_args({
            "request_object_signing_alg": "RS256",
            "request_object_encryption_alg": "RSA1_5",
            "request_object_encryption_enc": "A128CBC-HS256"})
        self.tests["pre"].extend([CheckEncryptedRequestObjectSupportALG,
                                  CheckEncryptedRequestObjectSupportENC,
                                  CheckSignedRequestObjectSupport])


class ReadRegistration(GetRequest):
    def call_setup(self):
        _client = self.conv.client
        self.request_args["access_token"] = _client.registration_access_token
        self.kw_args["authn_method"] = "bearer_header"
        self.kw_args["endpoint"] = _client.registration_response[
            "registration_client_uri"]


# =============================================================================


class AccessTokenRequest(PostRequest):
    request = "AccessTokenRequest"

    def __init__(self, conv):
        PostRequest.__init__(self, conv)
        self.tests["post"] = []
        # self.kw_args = {"authn_method": "client_secret_basic"}

    def call_setup(self):
        _pinfo = self.conv.client.provider_info
        try:
            _supported = _pinfo["token_endpoint_auth_methods_supported"]
        except KeyError:
            _supported = None

        if "authn_method" not in self.kw_args:
            if _supported:
                for meth in ["client_secret_basic", "client_secret_post",
                             "client_secret_jwt", "private_key_jwt"]:
                    if meth in _supported:
                        self.kw_args = {"authn_method": meth}
                        break
            else:
                self.kw_args = {"authn_method": "client_secret_basic"}
        elif _supported:
            try:
                assert self.kw_args["authn_method"] in _supported
            except AssertionError:
                raise NotSupported("Authn_method '%s' not supported" % (
                    self.kw_args["authn_method"]))


class AccessTokenRequestCSB(AccessTokenRequest):
    def __init__(self, conv):
        AccessTokenRequest.__init__(self, conv)
        self.kw_args = {"authn_method": "client_secret_basic"}


class AccessTokenRequestCSPost(AccessTokenRequest):
    def __init__(self, conv):
        AccessTokenRequest.__init__(self, conv)
        self.kw_args = {"authn_method": "client_secret_post"}


class AccessTokenRequestCSJWT(AccessTokenRequest):
    def __init__(self, conv):
        PostRequest.__init__(self, conv)
        self.kw_args = {"authn_method": "client_secret_jwt"}


class AccessTokenRequestPKJWT(AccessTokenRequest):
    def __init__(self, conv):
        PostRequest.__init__(self, conv)
        self.kw_args = {"authn_method": "private_key_jwt"}


class AccessTokenRequest_err(AccessTokenRequest):
    def __init__(self, conv):
        PostRequest.__init__(self, conv)
        self.tests["post"] = []


class AccessTokenRequestScope(AccessTokenRequest):
    def __init__(self, conv):
        AccessTokenRequest.__init__(self, conv)
        self.set_request_args({"scope": "scim"})
        self.tests["post"] = [CheckErrorResponse]


class AccessTokenRequestModRedirectURI1(AccessTokenRequest):
    def __init__(self, conv):
        AccessTokenRequest.__init__(self, conv)
        self.tests["post"] = [CheckErrorResponse]

    def call_setup(self):
        _client = self.conv.client
        _uri = _client.redirect_uris[0]
        # Mess with the redirect_uri dynamically
        _uri += "/xlevel"
        self.request_args["redirect_uri"] = _uri


class AccessTokenRequestModRedirectURI2(AccessTokenRequest):
    def __init__(self, conv):
        AccessTokenRequest.__init__(self, conv)
        self.tests["post"] = [CheckErrorResponse]

    def call_setup(self):
        _client = self.conv.client
        _uri = _client.redirect_uris[0]
        # Mess with the redirect_uri dynamically
        _uri += "?query=foo"
        self.request_args["redirect_uri"] = _uri


class AccessTokenRequestModRedirectURI3(AccessTokenRequest):
    def __init__(self, conv):
        AccessTokenRequest.__init__(self, conv)
        self.tests["post"] = [CheckErrorResponse]

    def call_setup(self):
        _client = self.conv.client
        _uri = _client.redirect_uris[0]
        # Mess with the redirect_uri dynamically
        part = urlparse(_uri)
        _uri = _uri.replace(part.path, "/")
        self.request_args["redirect_uri"] = _uri


class UserInfoRequestPostBearerHeader_err(PostRequest):
    request = "UserInfoRequest"

    def __init__(self, conv):
        PostRequest.__init__(self, conv)
        self.kw_args = {"authn_method": "bearer_header"}
        self.tests["post"] = [CheckErrorResponse]


class UserInfoRequestGetBearerHeader(GetRequest):
    request = "UserInfoRequest"

    def __init__(self, conv):
        GetRequest.__init__(self, conv)
        self.kw_args = {"authn_method": "bearer_header"}
        self.tests["post"] = [VerifyIDTokenUserInfoSubSame]


class UserInfoRequestPostBearerHeader(PostRequest):
    request = "UserInfoRequest"

    def __init__(self, conv):
        PostRequest.__init__(self, conv)
        self.kw_args = {"authn_method": "bearer_header"}
        self.tests["post"] = [VerifyIDTokenUserInfoSubSame]


class UserInfoRequestPostBearerHeaderJOSE(PostRequest):
    request = "UserInfoRequest"
    accept = "application/jwt"

    def __init__(self, conv):
        PostRequest.__init__(self, conv)
        self.kw_args = {"authn_method": "bearer_header"}
        self.tests["post"] = [VerifyIDTokenUserInfoSubSame]


class UserInfoRequestPostBearerBody(PostRequest):
    request = "UserInfoRequest"

    def __init__(self, conv):
        PostRequest.__init__(self, conv)
        self.kw_args = {"authn_method": "bearer_body"}
        self.tests["post"] = [VerifyIDTokenUserInfoSubSame]


class RefreshAccessToken(PostRequest):
    request = "RefreshAccessTokenRequest"

    def call_setup(self):
        # make sure there is a refresh_token
        try:
            _ = response_claim(self.conv, message.AccessTokenResponse,
                               "refresh_token")
        except MissingResponseClaim:
            raise UnSupported("No refresh_token")

        if "authn_method" not in self.kw_args:
            _pinfo = self.conv.provider_info
            if "token_endpoint_auth_methods_supported" in _pinfo:
                for meth in ["client_secret_basic", "client_secret_post",
                             "client_secret_jwt", "private_key_jwt"]:
                    if meth in _pinfo["token_endpoint_auth_methods_supported"]:
                        self.kw_args = {"authn_method": meth}
                        break
            else:
                self.kw_args = {"authn_method": "client_secret_basic"}


class RefreshAccessTokenPKJWT(PostRequest):
    request = "RefreshAccessTokenRequest"

    def call_setup(self):
        # make sure there is a refresh_token
        try:
            _ = response_claim(self.conv, message.AccessTokenResponse,
                               "refresh_token")
        except MissingResponseClaim:
            raise UnSupported("No refresh_token")

        self.kw_args = {"authn_method": "private_key_jwt"}


# -----------------------------------------------------------------------------


class AuthzResponse(UrlResponse):
    response = "AuthorizationResponse"
    _tests = {"post": [CheckAuthorizationResponse, VerifyState]}


class AuthzFormResponse(UrlResponse):
    response = "AuthorizationResponse"
    where = "body"
    _tests = {"post": [CheckAuthorizationResponse]}


class ImplicitAuthzResponse(AuthzResponse):
    _tests = {"post": [CheckAuthorizationResponse]}


class AuthzErrResponse(UrlResponse):
    response = "AuthorizationErrorResponse"


class RegistrationResponse(BodyResponse):
    response = "RegistrationResponse"

    def __call__(self, conv, response):
        _client = conv.client
        for prop in ["client_id"]:
            try:
                setattr(_client, prop, response[prop])
            except KeyError:
                pass


class AccessTokenResponse(BodyResponse):
    response = "AccessTokenResponse"

    def __init__(self):
        BodyResponse.__init__(self)
        self.tests = {"post": [VerifyAccessTokenResponse, VerifyISS,
                               VerifySignedIdToken]}


class AccessTokenResponseWNonce(AccessTokenResponse):
    response = "AccessTokenResponse"

    def __init__(self):
        AccessTokenResponse.__init__(self)
        self.tests["post"].append(VerifyNonce)


class AccessTokenResponseWKID(AccessTokenResponse):
    response = "AccessTokenResponse"

    def __init__(self):
        AccessTokenResponse.__init__(self)
        self.tests["post"].append(VerifySignedIdTokenHasKID)


class AccessTokenResponseUnsigned(BodyResponse):
    response = "AccessTokenResponse"

    def __init__(self):
        BodyResponse.__init__(self)
        self.tests = {"post": [VerifyAccessTokenResponse, VerifyISS,
                               VerifyUnSignedIdToken]}


class UserinfoResponse(BodyResponse):
    response = "OpenIDSchema"

    def __init__(self):
        BodyResponse.__init__(self)
        self.tests = {"post": [VerifyClaims]}


class CheckIdResponse(BodyResponse):
    response = "IdToken"


class ProviderConfigurationResponse(BodyResponse):
    response = "ProviderConfigurationResponse"


class ClientRegistrationErrorResponse(BodyResponse):
    response = "ClientRegistrationErrorResponse"


class AuthorizationErrorResponse(BodyResponse):
    response = "AuthorizationErrorResponse"


# ----------------------------------------------------------------------------


class DResponse(object):
    def __init__(self, status, ctype):
        self.content_type = ctype
        self.status = status

    def __getattr__(self, item):
        if item == "content-type":
            return self.content_type


class Discover(Operation):
    _tests = {"post": [ProviderConfigurationInfo, VerfyMTIEncSigAlgorithms,
                       CheckEncSigAlgorithms, VerifyOPEndpointsUseHTTPS],
              "pre": [DiscoveryConfig]}
    conv_param = "provider_info"
    request = "DiscoveryRequest"

    def __init__(self, conv, **kwargs):
        Operation.__init__(self, conv, **kwargs)
        self.request = "DiscoveryRequest"
        self.function = self.discover
        self.do_postop = True
        self.tests = self._tests.copy()

    def discover(self, client, orig_response="", content="", issuer="",
                 **kwargs):
        # Allow statically over-riding dynamic info
        over_ride = client.provider_info
        pcr = client.provider_config(issuer)
        if over_ride:
            pcr.update(over_ride)
            for key, val in over_ride.items():
                setattr(client, key, val)

        try:
            self.trace.info("%s" % client.keyjar)
        except SerializationNotPossible:
            pass

        self.trace.info("Provider info: %s" % pcr.to_dict())

        try:
            pcr.verify()
        except SchemeError:
            try:
                if client.allow["no_https_issuer"]:
                    pass
                else:
                    raise
            except KeyError:
                raise

        client.match_preferences(pcr)
        self.trace.info("Client behavior: %s" % client.behaviour)
        return "", DResponse(status=200, ctype="application/json"), pcr

    def post_op(self, result, conv, args):
        # Update the conv with the provider information
        # This overwrites what's there before. In some cases this might not
        # be preferable.

        if self.do_postop:
            attr = getattr(conv, self.conv_param, None)
            if attr is None:
                setattr(conv, self.conv_param, result[2].to_dict())
            else:
                attr.update(result[2].to_dict())


class Webfinger(Operation):
    # tests = {"post": [OidcIssuer]}
    request = None
    tests = {"post": [], "pre": []}

    def __init__(self, conv, **kwargs):
        Operation.__init__(self, conv, **kwargs)
        self.request = "WebFinger"
        self.function = self.discover
        self.do_postop = False

    @staticmethod
    def discover(*arg, **kwargs):
        wf = WebFinger(OIC_ISSUER)
        wf.httpd = PBase()
        wf.discovery_query(kwargs["principal"])

    def call_setup(self):
        pass

# ===========================================================================

PHASES = {
    "login": (AuthorizationRequestCode, AuthzResponse),
    # "login-nonce": (AuthorizationRequest_with_nonce, AuthzResponse),
    "login-wqc": (AuthorizationRequestCode_WQC, AuthzResponse),
    "login-ruwqc": (AuthorizationRequestCode_RUWQC, AuthzResponse),
    "login-ruwqc-err": (AuthorizationRequestCode_RUWQC_Err, AuthzErrResponse),
    "login-redirect-fault": (AuthorizationRequestMismatchingRedirectURI,
                             AuthorizationErrorResponse),
    "oic-login-implicit-no-nonce": (AuthorizationRequestWithoutNonce,
                                    AuthorizationErrorResponse),
    "verify": (ConnectionVerify, AuthzResponse),
    "oic-login": (AuthorizationRequestCode, AuthzResponse),
    "oic-login-uri": (AuthorizationRequestCodeUri, AuthzResponse),
    "oic-login-requri": (AuthorizationRequestCodeRequestInFile, AuthzResponse),
    "oic-login-request": (AuthorizationRequestCodeRequestParameter,
                          AuthzResponse),
    "oic-login-nonce": (AuthorizationRequestCodeWithNonce, AuthzResponse),
    "oic-login-code-no-nonce": (AuthorizationRequestCodeWithoutNonce,
                                AuthzResponse),
    "oic-login+profile": (AuthorizationRequestCodeScopeProfile, AuthzResponse),
    "oic-login+email": (AuthorizationRequestCodeScopeEMail, AuthzResponse),
    "oic-login+phone": (AuthorizationRequestCodeScopePhone, AuthzResponse),
    "oic-login+address": (AuthorizationRequestCodeScopeAddress, AuthzResponse),
    "oic-login+offline": (AuthorizationRequestCodeScopeOfflineAccess,
                          AuthzResponse),
    "oic-login+all": (AuthorizationRequestCodeScopeAll, AuthzResponse),
    "oic-login+spec1": (AuthorizationRequestCodeUIClaim1,
                        AuthzResponse),
    "oic-login+spec2": (AuthorizationRequestCodeUIClaim2,
                        AuthzResponse),
    "oic-login+spec3": (AuthorizationRequestCodeUIClaim3,
                        AuthzResponse),
    "oic-login-combine_claims": (AuthorizationRequestCodeUICombiningClaims,
                                 AuthzResponse),
    "oic-login-mixed_claims": (AuthorizationRequestCodeMixedClaims,
                               AuthzResponse),
    "oic-login+idtc1": (AuthorizationRequestCodeIDTClaim1, AuthzResponse),
    "oic-login+idtc2": (AuthorizationRequestCodeIDTClaim2, AuthzResponse),
    "oic-login+idtc3": (AuthorizationRequestCodeIDTClaim3, AuthzResponse),
    "oic-login+idtc6": (AuthorizationRequestCodeIDTClaim4, AuthzResponse),
    "oic-login+idtc4": (AuthorizationRequestCodeIDTMaxAge1, AuthzResponse),
    "oic-login+idtc5": (AuthorizationRequestCodeIDTMaxAge1000, AuthzResponse),
    "oic-login+idtc7": (AuthorizationRequestCodeIDTEmail, AuthzResponse),
    "oic-login+idtcX": (AuthorizationRequestCodeIDTClaimX, AuthzResponse),

    "oic-login+disp_page": (AuthorizationRequestCodeDisplayPage, AuthzResponse),
    "oic-login+disp_popup": (AuthorizationRequestCodeDisplayPopUp,
                             AuthzResponse),
    "oic-login+prompt_none": (AuthorizationRequestCodePromptNone,
                              AuthzErrResponse),
    "oic-login+prompt_login": (AuthorizationRequestCodePromptLogin,
                               AuthzResponse),
    "oic-login+prompt_none+idtoken": (
        AuthorizationRequestCodePromptNoneWithIdToken, AuthzResponse),
    "oic-login+prompt_none+request": (
        AuthorizationRequestCodePromptNoneWithSubClaim, AuthzResponse),
    "oic-login+request": (AuthorizationRequestCodeWithSubClaim, AuthzResponse),
    "oic-login-token": (AuthorizationRequestToken, ImplicitAuthzResponse),
    "oic-login-idtoken": (AuthorizationRequestIDToken, ImplicitAuthzResponse),
    "oic-login-code+token": (AuthorizationRequestCodeToken,
                             ImplicitAuthzResponse),
    "oic-login-code+idtoken": (AuthorizationRequestCodeIDToken,
                               ImplicitAuthzResponse),
    "oic-login-idtoken+token": (AuthorizationRequestIDTokenToken,
                                ImplicitAuthzResponse),
    "oic-login-code+idtoken+token": (AuthorizationRequestCodeIDTokenToken,
                                     ImplicitAuthzResponse),
    "oic-login-no-redirect": (AuthorizationRequestNoRedirectURI,
                              AuthzResponse),
    "oic-login-no-redirect-err": (AuthorizationRequestNoRedirectURI,
                                  AuthzErrResponse),
    "oic-login-formpost": (AuthorizationRequestCodeResponseModeFormPost,
                           AuthzFormResponse),
    "oic-login-ui_locale": (AuthorizationRequestUILocale, AuthzResponse),
    "oic-login-claims_locale": (AuthorizationRequestClaimsLocale,
                                AuthzResponse),
    "oic-login-login_hint": (AuthorizationRequestLoginHint, AuthzResponse),
    "oic-login-acr_values": (AuthorizationRequestAcrValues, AuthzResponse),
    #
    "access-token-request_csb": (AccessTokenRequestCSB, AccessTokenResponse),
    "access-token-request_csp": (AccessTokenRequestCSPost, AccessTokenResponse),
    "access-token-request": (AccessTokenRequest, AccessTokenResponse),
    "access-token-request_kid": (AccessTokenRequest, AccessTokenResponseWKID),
    "access-token-request_nonce": (
        AccessTokenRequest, AccessTokenResponseWNonce),
    "access-token-request_csj": (AccessTokenRequestCSJWT, AccessTokenResponse),
    "access-token-request_pkj": (AccessTokenRequestPKJWT, AccessTokenResponse),
    "access-token-request_err": (AccessTokenRequest_err, req.ErrorResponse),
    "access-token-request-scope": (AccessTokenRequestScope, req.ErrorResponse),
    "access-token-refresh": (RefreshAccessToken, AccessTokenResponse),
    "access-token-refresh_pkj": (RefreshAccessTokenPKJWT, AccessTokenResponse),
    "access-token-request-unsigned": (AccessTokenRequest,
                                      AccessTokenResponseUnsigned),
    "user-info-request_gbh": (UserInfoRequestGetBearerHeader, UserinfoResponse),
    "user-info-request_pbh": (UserInfoRequestPostBearerHeader,
                              UserinfoResponse),
    "user-info-request_gbh_jose": (UserInfoRequestPostBearerHeaderJOSE,
                                   UserinfoResponse),
    "user-info-request_pbb": (UserInfoRequestPostBearerBody, UserinfoResponse),
    "user-info-request_err": (UserInfoRequestPostBearerHeader_err,
                              req.ErrorResponse),
    "oic-registration": (RegistrationRequest, RegistrationResponse),
    "oic-registration-basic": (BasicRegistrationRequest, RegistrationResponse),
    "oic-registration-implicit": (ImplicitRegistrationRequest,
                                  RegistrationResponse),
    "oic-registration-hybrid": (HybridRegistrationRequest,
                                RegistrationResponse),
    "oic-registration-multi-redirect": (RegistrationRequestMULREDIR,
                                        RegistrationResponse),
    "oic-registration-wqc": (RegistrationRequest_WQC, RegistrationResponse),
    "oic-registration-wf": (RegistrationRequest_WF,
                            ClientRegistrationErrorResponse),
    "oic-registration-ke_csj": (RegistrationRequest_KeyExpCSJ,
                                RegistrationResponse),
    "oic-registration-ke_pkj": (RegistrationRequest_KeyExpPKJ,
                                RegistrationResponse),
    "oic-registration-policy+logo": (RegistrationRequestPolicyLogoTos,
                                     RegistrationResponse),
    "oic-registration-public_id": (RegistrationRequest_with_public_userid,
                                   RegistrationResponse),
    "oic-registration-pairwise_id": (RegistrationRequest_with_pairwise_userid,
                                     RegistrationResponse),
    "oic-registration-sector_id": (RegistrationRequest_SectorID,
                                   RegistrationResponse),
    "oic-registration-signed_userinfo": (
        RegistrationRequest_with_userinfo_signed, RegistrationResponse),
    "oic-registration-sector_id-err": (RegistrationRequest_SectorID_Err,
                                       ClientRegistrationErrorResponse),
    "oic-registration-unsigned_idtoken": (
        RegistrationRequestWithUnSignedIDToken, RegistrationResponse),
    "oic-registration-signed_idtoken": (
        RegistrationRequest_with_id_token_signed_response_alg,
        RegistrationResponse),
    "oic-registration-encrypted_userinfo": (
        RegistrationRequestEncUserinfo, RegistrationResponse),
    "oic-registration-signed+encrypted_userinfo": (
        RegistrationRequestSignEncUserinfo, RegistrationResponse),
    "oic-registration-encrypted_idtoken": (RegistrationRequestEncIDtoken,
                                           RegistrationResponse),
    "oic-registration-signed+encrypted_idtoken": (
        RegistrationRequestSignEncIDtoken, RegistrationResponse),
    "oic-registration-es-signed_idtoken": (RegistrationRequestESSigIDtoken,
                                           RegistrationResponse),
    "oic-registration-jwks": (RegistrationRequestJWKS, RegistrationResponse),
    "oic-registration-no_response_type": (RegistrationRequestNoResponseTypes,
                                          RegistrationResponse),
    "oic-registration-response_type-token": (
        RegistrationRequestResponseTypesToken, RegistrationResponse),
    "oic-registration-unsigned_request": (RegistrationRequestNoneSig,
                                          RegistrationResponse),
    "oic-registration-signed_request": (RegistrationRequestSig,
                                        RegistrationResponse),
    "oic-registration-sig+enc_request": (RegistrationRequestEnc,
                                         RegistrationResponse),
    "oic-registration-encrypted_request": (RegistrationRequestSigEnc,
                                           RegistrationResponse),
    "oic-registration-http-redirecturi": (RegistrationRequestHTTPREDIR,
                                          req.ErrorResponse),
    "provider-discovery": (Discover, ProviderConfigurationResponse),
    "provider-info": (ProviderRequest, ProviderConfigurationResponse),
    "oic-missing_response_type": (MissingResponseType, AuthzErrResponse),
    "read-registration": (ReadRegistration, RegistrationResponse),
    "oic-registration-multi-redirect_hosts": (
        RegistrationRequestMULREDIRMultHost, RegistrationResponse),
    "access-token-request-other-redirect_uri-1": (
        AccessTokenRequestModRedirectURI1, req.ErrorResponse),
    "access-token-request-other-redirect_uri-2": (
        AccessTokenRequestModRedirectURI2, req.ErrorResponse),
    "access-token-request-other-redirect_uri-3": (
        AccessTokenRequestModRedirectURI3, req.ErrorResponse),
    "intermission": TimeDelay,
    # "rotate_keys": RotateKeys,
    "rotate_sign_keys": RotateSigKeys,
    "rotate_enc_keys": RotateEncKeys,
    "note": Note,
    "rm_cookie": RmCookie,
    "expect_err": ExpectError,
    "webfinger": (Webfinger, None),
    "display_userinfo": DisplayUserInfo,
    "display_idtoken": DisplayIDToken
}

OWNER_OPS = []
USERINFO_REQUEST_AUTH_METHOD = "user-info-request_gbh"
UNKNOWN = []

FLOWS = {
    "Basic": {
        'OP-A-01': {
            "name": 'Request with response_type=code',
            "sequence": ["oic-registration-basic", "oic-login"],
            "endpoints": ["authorization_endpoint"],
            "mti": "MUST"
        },
        'OP-A-02': {
            "name": 'Authorization request missing the response_type parameter',
            "sequence": ["oic-registration-basic", "oic-missing_response_type"],
            "endpoints": ["authorization_endpoint"],
            "tests": [("verify-error", {"error": ["invalid_request",
                                                  "unsupported_response_type"]})],
            "mti": "MUST"
        },
        # =====================================================================
        'OP-B-01': {
            "name": 'Asymmetric ID Token signature with rs256',
            "sequence": ["oic-registration-basic", "oic-login",
                         "access-token-request"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "mti": "MUST"
        },
        'OP-B-02': {
            "name": 'IDToken has kid',
            "sequence": ["oic-registration-basic", "oic-login",
                         "access-token-request_kid"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "mti": "MUST"
        },
        'OP-B-03': {
            "name": 'ID Token has nonce when requested for code flow',
            "sequence": ["oic-registration-basic", "oic-login",
                         "access-token-request_nonce"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "mti": "MUST"
        },
        'OP-B-04': {
            "name": 'Requesting ID Token with max_age=1 seconds Restriction',
            "sequence": ["oic-registration-basic", "oic-login",
                         "access-token-request", "note",
                         "oic-registration-basic", "oic-login+idtc4"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "note": "This is to allow some time to pass. At least 1 second. "
                    "The result should be that you have to re-authenticate",
            "tests": [("multiple-sign-on", {})],
            "mti": "MUST"
        },
        'OP-B-05': {
            "name": 'Requesting ID Token with max_age=1000 seconds Restriction',
            "sequence": ["oic-login", "access-token-request",
                         "oic-login+idtc5"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "tests": [("multiple-sign-on", {})],
            "mti": "MUST"
        },
        'OP-B-06': {
            "name": 'Unsecured ID Token signature with none',
            "sequence": ["oic-registration-unsigned_idtoken",
                         "oic-login", "access-token-request-unsigned"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "mti": "MUST"
        },
        # =====================================================================
        'OP-C-01': {
            "name": 'UserInfo Endpoint Access with GET and bearer_header',
            "sequence": ["oic-login", "access-token-request",
                         "user-info-request_gbh"],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "MUST"
        },
        'OP-C-02': {
            "name": 'UserInfo Endpoint Access with POST and bearer_header',
            "sequence": ["oic-login", "access-token-request",
                         "user-info-request_pbh"],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "MUST"
        },
        'OP-C-03': {
            "name": 'UserInfo Endpoint Access with POST and bearer_body',
            "sequence": ["oic-login", "access-token-request",
                         "user-info-request_pbb"],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "MUST"
        },
        # =====================================================================
        'OP-D-01': {
            "name": 'Login no nonce, code flow',
            "sequence": ["oic-login-code-no-nonce", "access-token-request"],
            "endpoints": ["authorization_endpoint"],
            "mti": "MUST"
        },
        # =====================================================================
        'OP-E-01': {
            "name": 'Scope Requesting profile Claims',
            "sequence": ["oic-login+profile", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
        'OP-E-02': {
            "name": 'Scope Requesting email Claims',
            "sequence": ["oic-login+email", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
        'OP-E-03': {
            "name": 'Scope Requesting address Claims',
            "sequence": ["oic-login+address", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
        'OP-E-04': {
            "name": 'Scope Requesting phone Claims',
            "sequence": ["oic-login+phone", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
        'OP-E-05': {
            "name": 'Scope Requesting all Claims',
            "sequence": ["oic-login+all", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
        # =====================================================================
        'OP-F-01': {
            "name": 'Request with display=page',
            "sequence": ["oic-login+disp_page", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "mti": "No err"
        },
        'OP-F-02': {
            "name": 'Request with display=popup',
            "sequence": ["oic-login+disp_popup", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "mti": "No err"
        },
        # =====================================================================
        'OP-G-01': {
            "name": 'Request with prompt=login means it SHOULD prompt the End-User '
                    'for reauthentication',
            "sequence": ["oic-login+prompt_login"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "mti": "MUST"
        },
        'OP-G-02': {
            "name": 'Request with prompt=none',
            "sequence": ["rm_cookie", "oic-login+prompt_none"],
            "endpoints": ["authorization_endpoint"],
            "tests": [("verify-error", {"error": ["login_required",
                                                  "interaction_required",
                                                  "session_selection_required",
                                                  "consent_required"]})],
            "mti": "MUST"
        },
        # =====================================================================
        'OP-H-01': {
            "name": 'Request with response_type=code and extra query component',
            "sequence": ["login-wqc"],
            "endpoints": ["authorization_endpoint"],
            "profile": {"Basic": "MUST", "Implicit": "MUST", "Hybrid": "MUST",
                        "Self-issued": "MUST"}
        },
        'OP-H-02': {
            "name": 'Using prompt=none with user hint through id_token_hint',
            "sequence": ["oic-login", "access-token-request", 'rm_cookie',
                         "oic-login+prompt_none+idtoken"],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "profile": {"Basic": "SHOULD", "Implicit": "SHOULD",
                        "Hybrid": "SHOULD", "Self-issued": "SHOULD"},
            "cache": ["id_token"]
        },
        'OP-H-03': {
            "name": 'login_hint',
            "sequence": ["oic-login-login_hint"],
            "endpoints": ["authorization_endpoint"],
            "profile": {"Basic": "No err", "Implicit": "No err",
                        "Hybrid": "No err", "Self-issued": "No err"}
        },
        'OP-H-04': {
            "name": 'ui_locales',
            "sequence": ['rm_cookie', 'note', "oic-login-ui_locale"],
            "endpoints": ["authorization_endpoint"],
            "note": "The user interface may now use the locale of choice",
            "profile": {"Basic": "No err", "Implicit": "No err",
                        "Hybrid": "No err", "Self-issued": "No err"}
        },
        'OP-H-05': {
            "name": 'claims_locales',
            "sequence": ["note", "oic-login-claims_locale", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD, 'display_userinfo'],
            "endpoints": ["authorization_endpoint"],
            "note": "Claims may now be returned in the locale of choice",
            "profile": {"Basic": "No err", "Implicit": "No err",
                        "Hybrid": "No err", "Self-issued": "No err"}
        },
        'OP-H-06': {
            "name": 'acr_values',
            "sequence": ["oic-login-acr_values"],
            "endpoints": ["authorization_endpoint"],
            "profile": {"Basic": "No err", "Implicit": "No err",
                        "Hybrid": "No err", "Self-issued": "No err"}
        },
        # =====================================================================
        'OP-I-01': {
            "name": 'Trying to use access code twice should result in an error',
            "sequence": ["oic-login", "access-token-request",
                         "access-token-request_err"],
            "reference": "http://tools.ietf.org/html/draft-ietf-oauth-v2-31"
                         "#section-4.1",
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "tests": [("verify-bad-request-response", {})],
            "profile": {"Basic": "MUST", "Hybrid": "MUST"}
        },
        'OP-I-02': {
            "name": 'Trying to use access code twice should result in '
                    'revoking previous issued tokens',
            "reference": "http://tools.ietf.org/html/draft-ietf-oauth-v2-31"
                         "#section-4.1",
            "sequence": ["oic-login", "access-token-request",
                         "access-token-request_err", "user-info-request_err"],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "tests": [("verify-bad-request-response", {})],
            "profile": {"Basic": "SHOULD", "Hybrid": "SHOULD"}
        },
        # =====================================================================
        'OP-J-01': {
            "name": 'The sent redirect_uri does not match the registered',
            "sequence": ["expect_err", "login-redirect-fault"],
            "endpoints": ["authorization_endpoint"],
            "note": "The next request should result in the OpenID Connect Provider "
                    "returning an error message to your web browser.",
            "profile": {"Basic": "MUST", "Implicit": "MUST", "Hybrid": "MUST",
                        "Self-issued": "MUST"}
        },
        'OP-J-02': {
            "name": 'Reject request without redirect_uri when multiple registered',
            "sequence": ["oic-registration-multi-redirect",
                         "expect_err", "oic-login-no-redirect-err"],
            "endpoints": ["authorization_endpoint"],
            # "note": "The next request should result in the OpenID Connect
            # Provider "
            # "returning an error message to your web browser.",
            "profile": {"Basic": "MUST", "Implicit": "MUST", "Hybrid": "MUST",
                        "Self-issued": "MUST"}
        },
        'OP-J-03': {
            "name": 'Request with redirect_uri with query component',
            "sequence": ["login-ruwqc"],
            "endpoints": ["authorization_endpoint"],
            "profile": {"Basic": "MUST", "Implicit": "MUST", "Hybrid": "MUST",
                        "Self-issued": "MUST"}
        },
        'OP-J-04': {
            "name": 'Rejects redirect_uri when Query Parameter Does Not Match',
            "sequence": ["oic-registration-wqc", 'expect_err', "login-ruwqc-err"],
            "endpoints": ["registration_endpoint", "authorization_endpoint"],
            "reference": "http://tools.ietf.org/html/draft-ietf-oauth-v2-31"
                         "#section-3.1.2",
            "profile": {"Basic": "MUST", "Implicit": "MUST", "Hybrid": "MUST",
                        "Self-issued": "MUST"}
        },
        'OP-J-05': {
            "name": 'Registration where a redirect_uri has a query component',
            "sequence": ["oic-registration-wqc"],
            "endpoints": ["registration_endpoint"],
            "reference": "http://tools.ietf.org/html/draft-ietf-oauth-v2-31"
                         "#section-3.1.2",
            "profile": {"Dynamic": "MUST"}
        },
        'OP-J-06': {
            "name": 'Reject registration where a redirect_uri has a fragment',
            "sequence": ["oic-registration-wf"],
            "endpoints": ["registration_endpoint"],
            "reference": "http://tools.ietf.org/html/draft-ietf-oauth-v2-31"
                         "#section-3.1.2",
            "profile": {"Dynamic": "MUST"}
        },
        'OP-J-07': {
            "name": 'Reject registration with invalid redirect_uris',
            "sequence": ["oic-registration-http-redirecturi"],
            "endpoints": [],
            "profile": {"Dynamic": "MUST"}
        },
        'OP-J-08': {
            "name": 'No redirect_uri in request with one registered',
            "sequence": ["oic-registration", "expect_err",
                         "oic-login-no-redirect-err"],
            "endpoints": ["registration_endpoint", "authorization_endpoint"],
        },
        # =====================================================================
        'OP-K-01': {
            "name": 'Access token request with client_secret_basic authentication',
            # Should register token_endpoint_auth_method=client_secret_basic
            "sequence": ["oic-login", "access-token-request_csb"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "profile": {"Basic": "MUST"}
        },
        'OP-K-02': {
            "name": 'Access token request with client_secret_post authentication',
            # Should register token_endpoint_auth_method=client_secret_post
            "sequence": ["oic-login", "access-token-request_csp"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "profile": {"Basic": "MUST"}
        },
        'OP-K-03': {
            "name": 'Access token request with public_key_jwt authentication',
            "sequence": ["oic-registration-ke_pkj", "oic-login",
                         "access-token-request_pkj"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
        },
        'OP-K-04': {
            "name": 'Access token request with client_secret_jwt authentication',
            "sequence": ["oic-registration-ke_csj", "oic-login",
                         "access-token-request_csj"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
        },
        # =====================================================================
        'OP-L-01': {
            "name": 'Publish openid-configuration discovery information',
            "descr": 'Exchange in which Client Discovers and Uses OP Information',
            "sequence": [],
            "endpoints": [],
            "block": ["registration", "key_export"],
            "profile": {"Config": "MUST", "Dynamic": "MUST"}
        },
        'OP-L-02': {
            "name": 'Verify that jwks_uri and claims_supported are published',
            "sequence": ["provider-discovery"],
            "tests": [("providerinfo-has-jwks_uri", {}),
                      ("providerinfo-has-claims_supported", {})],
            "profile": {"Config": "MUST", "Dynamic": "MUST"}
        },
        'OP-L-03': {
            "name": 'Keys in OP JWKs well formed',
            "sequence": ["provider-discovery"],
            "tests": [("verify-base64url", {})],
            "profile": {"Config": "MUST", "Dynamic": "MUST"}
        },
        'OP-L-04': {
            "name": 'Verify that registration_endpoint is published',
            "sequence": ["provider-discovery"],
            "tests": [("verify-op-has-registration-endpoint", {})],
            "profile": {"Dynamic": "MUST"}
        },
        'OP-L-05': {
            "name": 'Can Discover Identifiers using E-Mail/URL Syntax',
            "sequence": ["webfinger"],
            "block": ["registration", "key_export"],
            "profile": {"Dynamic": "MUST"}
        },
        # =====================================================================
        # 'OP-M-01': {
        # "name": '',
        # "sequence": [""],
        #     "block": [],
        #     "profile": {"Basic":"MUST","Implicit":"MUST","Hybrid":
        # "MUST","Self-issued": "MUST","Dynamic": "MUST"}
        # },
        'OP-M-02': {
            "name": 'Registration with policy_uri and logo_uri',
            "sequence": ["rm_cookie", "oic-registration-policy+logo",
                         "oic-login"],
            "endpoints": ["registration_endpoint", "authorization_endpoint"],
            "profile": {"Basic": "SHOULD", "Implicit": "SHOULD",
                        "Hybrid": "SHOULD", "Self-issued": "SHOULD"},
        },
        'OP-M-03': {
            "name": 'Client registration Request',
            "sequence": ["oic-registration"],
            "endpoints": ["registration_endpoint"],
            "profile": {"Dynamic": "MUST"}
        },
        'OP-M-04': {
            "name": 'Registration of static keys',
            "sequence": ["oic-registration-jwks", "oic-login",
                         "access-token-request_csj"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "profile": {"Dynamic": "MUST"}
        },
        'OP-M-05': {
            "name": 'Incorrect registration of sector_identifier_uri',
            "sequence": ["oic-registration-sector_id-err"],
            "endpoints": ["registration_endpoint"],
            "profile": {"Dynamic": "MUST"}
        },
        'OP-M-06': {
            "name": 'Registering and then read the client info',
            "sequence": ["oic-registration", "read-registration"],
        },
        'OP-M-07': {
            "name": 'Registration of wish for public sub',
            "sequence": ["oic-registration-public_id", "oic-login",
                         "access-token-request"],
            "endpoints": ["registration_endpoint"],
        },
        'OP-M-08': {
            "name": 'Registration of wish for pairwise sub',
            "sequence": ["oic-registration-pairwise_id", "oic-login",
                         "access-token-request", USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["registration_endpoint", "authorization_endpoint",
                          "token_endpoint", "userinfo_endpoint"],
        },
        # =====================================================================
        # 'OP-N-01': {
        #     "profile": {"Config": "MUST","Dynamic": "MUST"}
        # },
        'OP-N-02': {
            "name": 'Request access token, change RSA sign key and request another '
                    'access token',
            "sequence": ["oic-registration-ke_csj", "oic-login",
                         "access-token-request_pkj", "rotate_sign_keys",
                         "access-token-refresh_pkj"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "profile": {"Dynamic": "MUST"}
        },
        'OP-N-03': {
            # where is the RPs encryption key used => userinfo encryption
            # How do I get the OP to use the new enc key ?
            "name": 'Request encrypted user info, change RSA enc key and request '
                    'user info again',
            "sequence": ["oic-registration-ke_csj", "oic-login",
                         "access-token-request_pkj", "rotate_enc_keys",
                         "access-token-refresh_pkj"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
        },
        # =====================================================================
        'OP-O-01': {
            "name": 'Support request_uri Request Parameter with unSigned Request',
            "sequence": ["oic-registration-unsigned_request",
                         "oic-login-requri"],
            "endpoints": ["authorization_endpoint"],
            "profile": {"Basic": "No err", "Implicit": "No err",
                        "Hybrid": "No err", "Self-issued": "No err",
                        "Dynamic": "MUST"}
        },
        'OP-O-02': {
            "name": 'Support request_uri Request Parameter with Signed Request',
            "sequence": ["oic-registration-signed_request",
                         "oic-login-requri"],
            "endpoints": ["authorization_endpoint"],
            "profile": {"Dynamic": "MUST"}
        },
        'OP-O-03': {
            "name": 'Support request_uri Request Parameter with Encrypted Request',
            "sequence": ["oic-registration-encrypted_request",
                         "oic-login-requri"],
            "endpoints": ["authorization_endpoint"],
        },
        'OP-O-04': {
            "name": 'Support request_uri Request Parameter with Signed and '
                    'Encrypted Request',
            "sequence": ["oic-registration-sig+enc_request",
                         "oic-login-requri"],
            "endpoints": ["authorization_endpoint"],
        },
        # =====================================================================
        'OP-P-01': {
            "name": 'Support request Request Parameter with unSigned Request',
            "sequence": ["oic-registration-unsigned_request",
                         "oic-login-request"],
            "endpoints": ["authorization_endpoint"],
            "profile": {"Basic": "No err", "Implicit": "No err",
                        "Hybrid": "No err", "Self-issued": "No err"}
        },
        'OP-P-02': {
            "name": 'Support request Request Parameter with Signed Request',
            "sequence": ["oic-registration-signed_request",
                         "oic-login-request"],
            "endpoints": ["authorization_endpoint"],
        },
        # =====================================================================
        'OP-Q-01': {
            "name": 'Claims Request with Essential name Claim',
            "sequence": ["oic-login+spec1", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
    },
    "Implicit": {
        'OP-A-02': {
            "name": 'Authorization request missing the response_type parameter',
            "sequence": ["oic-registration-implicit", "oic-missing_response_type"],
            "endpoints": ["authorization_endpoint"],
            "tests": [("verify-error", {"error": ["invalid_request",
                                                  "unsupported_response_type"]})],
            "mti": "MUST"
        },
        'OP-A-03': {
            "name": 'Request with response_type=id_token',
            "sequence": ["oic-registration-implicit", "oic-login-idtoken"],
            "endpoints": ["authorization_endpoint"],
            "mti": "MUST"
        },
        'OP-A-04': {
            "name": 'Request with response_type=id_token token',
            "sequence": ["oic-registration-implicit", 'oic-login-idtoken+token'],
            "endpoints": ["authorization_endpoint"],
            "mti": "MUST"
        },
        'OP-B-01-I': {
            "name": 'Asymmetric ID Token signature with rs256',
            "sequence": ["oic-registration-implicit", "oic-login-idtoken"],
            "endpoints": ["authorization_endpoint"],
            "mti": "MUST"
        },
        'OP-B-02-I': {
            "name": 'IDToken has kid',
            "sequence": ["oic-registration-implicit", "oic-login"],
            "endpoints": ["authorization_endpoint"],
            "mti": "MUST"
        },
        'OP-B-04-I': {
            "name": 'Requesting ID Token with max_age=1 seconds Restriction',
            "sequence": ["oic-registration-implicit", "oic-login", "note",
                         "oic-registration-implicit", "oic-login+idtc4"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "note": "This is to allow some time to pass. At least 1 second. "
                    "The result should be that you have to re-authenticate",
            "tests": [("multiple-sign-on", {})],
            "mti": "MUST"
        },
        'OP-C-01': {
            "name": 'UserInfo Endpoint Access with GET and bearer_header',
            "sequence": ["oic-login", "access-token-request",
                         "user-info-request_gbh"],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "MUST"
        },
        'OP-C-02': {
            "name": 'UserInfo Endpoint Access with POST and bearer_header',
            "sequence": ["oic-login", "access-token-request",
                         "user-info-request_pbh"],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "MUST"
        },
        'OP-C-03': {
            "name": 'UserInfo Endpoint Access with POST and bearer_body',
            "sequence": ["oic-login", "access-token-request",
                         "user-info-request_pbb"],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "MUST"
        },
        'OP-D-02': {
            "name": 'Login no nonce, implicit flow',
            "sequence": ["oic-login-implicit-no-nonce"],
            "endpoints": ["authorization_endpoint"],
            "tests": [("verify-error", {"error": ["invalid_request",
                                                  "unsupported_response_type"]})],
            "mti": "MUST"
        },
        'OP-E-01': {
            "name": 'Scope Requesting profile Claims',
            "sequence": ["oic-login+profile", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
        'OP-E-02': {
            "name": 'Scope Requesting email Claims',
            "sequence": ["oic-login+email", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
        'OP-E-03': {
            "name": 'Scope Requesting address Claims',
            "sequence": ["oic-login+address", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
        'OP-E-04': {
            "name": 'Scope Requesting phone Claims',
            "sequence": ["oic-login+phone", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
        'OP-E-05': {
            "name": 'Scope Requesting all Claims',
            "sequence": ["oic-login+all", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
        'OP-F-01': {
            "name": 'Request with display=page',
            "sequence": ["oic-login+disp_page", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "mti": "No err"
        },
        'OP-F-02': {
            "name": 'Request with display=popup',
            "sequence": ["oic-login+disp_popup", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "mti": "No err"
        },
        'OP-G-01': {
            "name": 'Request with prompt=login means it SHOULD prompt the End-User '
                    'for reauthentication',
            "sequence": ["oic-login+prompt_login"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "mti": "MUST"
        },
        'OP-G-02': {
            "name": 'Request with prompt=none',
            "sequence": ["rm_cookie", "oic-login+prompt_none"],
            "endpoints": ["authorization_endpoint"],
            "tests": [("verify-error", {"error": ["login_required",
                                                  "interaction_required",
                                                  "session_selection_required",
                                                  "consent_required"]})],
            "mti": "MUST"
        },
    },
    "Hybrid": {
        'OP-A-02': {
            "name": 'Authorization request missing the response_type parameter',
            "sequence": ["oic-registration-hybrid", "oic-missing_response_type"],
            "endpoints": ["authorization_endpoint"],
            "tests": [("verify-error", {"error": ["invalid_request",
                                                  "unsupported_response_type"]})],
            "mti": "MUST"
        },
        'OP-A-05': {
            "name": 'Request with response_type=code id_token',
            "sequence": ["oic-registration-hybrid", 'oic-login-code+idtoken'],
            "endpoints": ["authorization_endpoint"],
            "tests": [('check-nonce', {})],
            "mti": "MUST"
        },
        'OP-A-06': {
            "name": 'Request with response_type=code token',
            "sequence": ["oic-login-code+token"],
            "endpoints": ["authorization_endpoint"],
            "mti": "MUST"
        },
        'OP-A-07': {
            "name": 'Request with response_type=code id_token token',
            "sequence": ['oic-login-code+idtoken+token'],
            "endpoints": ["authorization_endpoint", ],
            "mti": "MUST"
        },
        'OP-B-01': {
            "name": 'Asymmetric ID Token signature with rs256',
            "sequence": ["oic-registration-implicit", "oic-login-code+idtoken"],
            "endpoints": ["authorization_endpoint"],
            "mti": "MUST"
        },
        'OP-B-02': {
            "name": 'IDToken has kid',
            "sequence": ["oic-registration-hybrid", "oic-login"],
            "endpoints": ["authorization_endpoint"],
            "mti": "MUST"
        },
        'OP-B-04': {
            "name": 'Requesting ID Token with max_age=1 seconds Restriction',
            "sequence": ["oic-registration-hybrid", "oic-login", "note",
                         "oic-registration-hybrid", "oic-login+idtc4"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "note": "This is to allow some time to pass. At least 1 second. "
                    "The result should be that you have to re-authenticate",
            "tests": [("multiple-sign-on", {})],
            "mti": "MUST"
        },
        'OP-B-07': {
            "name": 'Request with response_type=id_token token',
            "sequence": ['oic-login-idtoken+token'],
            "endpoints": ["authorization_endpoint"],
            "mti": "MUST"
        },
        'OP-B-08': {
            "name": 'Request with response_type=code id_token',
            "sequence": ['oic-login-code+idtoken', "access-token-request"],
            "endpoints": ["authorization_endpoint"],
            "tests": [('check-nonce', {})],
            "mti": "MUST"
        },
        'OP-C-01': {
            "name": 'UserInfo Endpoint Access with GET and bearer_header',
            "sequence": ["oic-login", "access-token-request",
                         "user-info-request_gbh"],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "MUST"
        },
        'OP-C-02': {
            "name": 'UserInfo Endpoint Access with POST and bearer_header',
            "sequence": ["oic-login", "access-token-request",
                         "user-info-request_pbh"],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "MUST"
        },
        'OP-C-03': {
            "name": 'UserInfo Endpoint Access with POST and bearer_body',
            "sequence": ["oic-login", "access-token-request",
                         "user-info-request_pbb"],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "MUST"
        },
        'OP-D-02': {
            "name": 'Login no nonce, implicit flow',
            "sequence": ["oic-login-implicit-no-nonce"],
            "endpoints": ["authorization_endpoint"],
            "tests": [("verify-error", {"error": ["invalid_request",
                                                  "unsupported_response_type"]})],
            "mti": "MUST"
        },
        'OP-E-01': {
            "name": 'Scope Requesting profile Claims',
            "sequence": ["oic-login+profile", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
        'OP-E-02': {
            "name": 'Scope Requesting email Claims',
            "sequence": ["oic-login+email", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
        'OP-E-03': {
            "name": 'Scope Requesting address Claims',
            "sequence": ["oic-login+address", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
        'OP-E-04': {
            "name": 'Scope Requesting phone Claims',
            "sequence": ["oic-login+phone", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
        'OP-E-05': {
            "name": 'Scope Requesting all Claims',
            "sequence": ["oic-login+all", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
        'OP-F-01': {
            "name": 'Request with display=page',
            "sequence": ["oic-login+disp_page", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "mti": "No err"
        },
        'OP-F-02': {
            "name": 'Request with display=popup',
            "sequence": ["oic-login+disp_popup", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "mti": "No err"
        },
        'OP-G-01': {
            "name": 'Request with prompt=login means it SHOULD prompt the End-User '
                    'for reauthentication',
            "sequence": ["oic-login+prompt_login"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "mti": "MUST"
        },
        'OP-G-02': {
            "name": 'Request with prompt=none',
            "sequence": ["rm_cookie", "oic-login+prompt_none"],
            "endpoints": ["authorization_endpoint"],
            "tests": [("verify-error", {"error": ["login_required",
                                                  "interaction_required",
                                                  "session_selection_required",
                                                  "consent_required"]})],
            "mti": "MUST"
        },
    },
    "Self-issued": {
        'OP-A-02': {
            "name": 'Authorization request missing the response_type parameter',
            "sequence": ["oic-registration-basic", "oic-missing_response_type"],
            "endpoints": ["authorization_endpoint"],
            "tests": [("verify-error", {"error": ["invalid_request",
                                                  "unsupported_response_type"]})],
            "mti": "MUST"
        },
        'OP-A-03': {
            "name": 'Request with response_type=id_token',
            "sequence": ["oic-registration-implicit", "oic-login-idtoken"],
            "endpoints": ["authorization_endpoint"],
            "mti": "MUST"
        },
        'OP-D-02': {
            "name": 'Login no nonce, implicit flow',
            "sequence": ["oic-login-implicit-no-nonce"],
            "endpoints": ["authorization_endpoint"],
            "tests": [("verify-error", {"error": ["invalid_request",
                                                  "unsupported_response_type"]})],
            "mti": "MUST"
        },
        'OP-E-01': {
            "name": 'Scope Requesting profile Claims',
            "sequence": ["oic-login+profile", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
        'OP-E-02': {
            "name": 'Scope Requesting email Claims',
            "sequence": ["oic-login+email", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
        'OP-E-03': {
            "name": 'Scope Requesting address Claims',
            "sequence": ["oic-login+address", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
        'OP-E-04': {
            "name": 'Scope Requesting phone Claims',
            "sequence": ["oic-login+phone", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
        'OP-E-05': {
            "name": 'Scope Requesting all Claims',
            "sequence": ["oic-login+all", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "mti": "No err"
        },
        'OP-F-01': {
            "name": 'Request with display=page',
            "sequence": ["oic-login+disp_page", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "mti": "No err"
        },
        'OP-F-02': {
            "name": 'Request with display=popup',
            "sequence": ["oic-login+disp_popup", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "mti": "No err"
        },
    },
    "Config": {
        'OP-B-06': {
            "name": 'Unsecured ID Token signature with none',
            "sequence": ["oic-registration-unsigned_idtoken",
                         "oic-login", "access-token-request-unsigned"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "mti": "MUST"
        },
    },
    "Dynamic": {
        'OP-B-06': {
            "name": 'Unsecured ID Token signature with none',
            "sequence": ["oic-registration-unsigned_idtoken",
                         "oic-login", "access-token-request-unsigned"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "mti": "MUST"
        },
        'OP-C-04': {
            "name": 'RP registers userinfo_signed_response_alg to signal that it '
                    'wants signed UserInfo returned',
            "sequence": ["oic-registration-signed_userinfo", "oic-login",
                         "access-token-request", USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "tests": [("asym-signed-userinfo", {})],
            "mti": "MUST"
        },
    },
    "Extra": {
        'OP-A-08': {
            "name": 'Specifying the authn response to be in the form of a '
                    'form post',
            "sequence": ["oic-login-formpost"],
            "endpoints": ["authorization_endpoint"],
        },
        'OP-B-09': {
            "name": 'RP wants symmetric IdToken signature',
            "sequence": ["oic-registration-signed_idtoken", "oic-login",
                         "access-token-request"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "tests": [("sym-signed-idtoken", {})],
        },
        'OP-B-10': {
            "name": 'RP wants asymmetric elliptic IdToken signature',
            "sequence": ["oic-registration-es-signed_idtoken", "oic-login",
                         "access-token-request"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "tests": [("es-signed-idtoken", {})],
        },
        'OP-B-11': {
            "name": 'Can Provide Signed and Encrypted ID Token Response',
            "sequence": ["oic-registration-signed+encrypted_idtoken", "oic-login",
                         "access-token-request"],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "tests": [("signed-encrypted-idtoken", {})],
        },
        'OP-C-05': {
            "name": 'Can Provide Encrypted UserInfo Response',
            "sequence": ["oic-registration-encrypted_userinfo", "oic-login",
                         "access-token-request", USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "tests": [("encrypted-userinfo", {})],
        },
        'OP-C-06': {
            "name": 'Can Provide Signed and Encrypted UserInfo Response',
            "sequence": ["oic-registration-signed+encrypted_userinfo", "oic-login",
                         "access-token-request", USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "tests": [("encrypted-userinfo", {})],
        },
        'OP-Q-02': {
            "name": 'Support claims request specifying sub value',
            "sequence": ["oic-login", "access-token-request", 'rm_cookie',
                         "oic-login+request"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "cache": ["id_token"]
        },
        'OP-Q-03': {
            "name": 'Using prompt=none with user hint through sub in request',
            "sequence": ["oic-login", "access-token-request", 'rm_cookie',
                         "oic-login+prompt_none+request"],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "cache": ["id_token"]
        },
        'OP-Q-04': {
            "name": 'Requesting ID Token with Email claims',
            "sequence": ["oic-login+idtc7", "access-token-request"],
            "endpoints": ["authorization_endpoint", "token_endpoint"],
            "tests": [("verify-id-token", {})],
        },
        'OP-Q-05': {
            "name": 'Supports Returning Different Claims in ID Token and UserInfo '
                    'Endpoint',
            "sequence": ["oic-login-mixed_claims", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "tests": [("verify-id-token", {}), ("verify-userinfo", {})],
        },
        'OP-Q-06': {
            "name": 'Supports Combining Claims Requested with scope and claims '
                    'Request Parameter',
            "sequence": ["oic-login-combine_claims", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "tests": [("verify-userinfo", {})]
        },
        'OP-Q-07': {
            "name": 'Claims Request with Voluntary email and picture Claims',
            "sequence": ["oic-login+spec2", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
        },
        'OP-Q-08': {
            "name": (
                'Claims Request with Essential name and Voluntary email and '
                'picture Claims'),
            "sequence": ["oic-login+spec3", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
        },
        'OP-Q-09': {
            "name": 'Requesting ID Token with Essential auth_time Claim',
            "sequence": ["oic-login+idtcX", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "tests": [("verify-id-token", {"auth_time": "essential"})],
        },
        'OP-Q-10': {
            "name": 'Requesting ID Token with Essential acr Claim',
            "sequence": ["oic-login+idtc6", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            #"tests": [("verify-id-token", {"acr": None})],
        },
        'OP-Q-11': {
            "name": 'Requesting ID Token with Voluntary acr Claim',
            "sequence": ["oic-login+idtc3", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "tests": [("verify-id-token", {"acr": "essential"})],
        },
        'OP-Q-12': {
            "name": 'Requesting ID Token with Essential specific acr Claim',
            "sequence": ["oic-login+idtc2", "access-token-request",
                         USERINFO_REQUEST_AUTH_METHOD],
            "endpoints": ["authorization_endpoint", "token_endpoint",
                          "userinfo_endpoint"],
            "tests": [("verify-id-token", {"acr": {"values": UNKNOWN}})],
        },
    }
}