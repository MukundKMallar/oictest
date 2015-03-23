#!/usr/bin/env python
from oic.exception import PyoidcError
from oic.exception import UnSupported

__author__ = 'rohe0002'

import sys

from oic.oauth2.message import Message
from oic.oic import RegistrationResponse

from rrtest import tool, FatalError

ORDER = ["url", "response", "content"]


def endpoint(client, base):
    for _endp in client._endpoints:
        if getattr(client, _endp) == base:
            return True

    return False


class Conversation(tool.Conversation):
    def __init__(self, client, config, trace, interaction, msg_factory,
                 check_factory, features=None, verbose=False,
                 expect_exception=False, **extra_args):
        tool.Conversation.__init__(self, client, config, trace,
                                   interaction, check_factory, msg_factory,
                                   features, verbose, expect_exception,
                                   **extra_args)
        self.cis = []
        # self.item = []
        self.keyjar = self.client.keyjar
        self.position = ""
        self.last_response = None
        self.last_content = None
        self.accept_exception = False
        self.creq = None
        self.cresp = None
        self.msg_factory = msg_factory
        self.login_page = None
        self.response_message = None
        self.info = None
        self.AuthorizationRequest = None
        self.etag = {}

    def my_endpoints(self):
        return self.client.redirect_uris

    def handle_result(self):
        try:
            self.response_spec = resp = self.cresp()
        except TypeError:
            self.response_spec = None
            return True

        self.info = None
        self.response_message = None

        response = self.last_response
        resp_type = resp.ctype

        err = None
        _errtxt = ""
        if isinstance(response, dict):
            _cli = self.client
            _resp = self.msg_factory(resp.response)
            _qresp = self.client.parse_response(
                _resp, response, "dict", self.state,
                keyjar=self.keyjar, client_id=_cli.client_id,
                scope="openid", opponent_id=_cli.provider_info["issuer"])
            self.response_message = _qresp
            self.protocol_response.append((_qresp, self.info))
        else:
            try:
                ctype = response.headers["content-type"]
                if "application/jwt" in ctype:
                    resp_type = "jwt"
            except (AttributeError, TypeError, KeyError):
                pass

            if response.status_code >= 400:
                pass
            elif not self.position:
                if isinstance(self.last_content, Message):
                    self.response_message = self.last_content
                elif response.status_code == 200:
                    self.info = self.last_content
            elif resp.where == "url" or response.status_code == 302:
                try:
                    self.info = response.headers["location"]
                    resp_type = "urlencoded"
                except KeyError:
                    try:
                        _check = getattr(self.creq, "interaction_check", None)
                    except AttributeError:
                        _check = None

                    if _check:
                        return False
                    else:
                        self.do_check("missing-redirect")
            else:
                self.do_check("check_content_type_header")
                self.info = self.last_content

            if self.info and resp.response:
                if isinstance(resp.response, basestring):
                    response = self.msg_factory(resp.response)
                else:
                    response = resp.response

                self.response_type = response.__name__
                try:
                    _cli = self.client
                    _qresp = self.client.parse_response(
                        response, self.info, resp_type, self.state,
                        keyjar=self.keyjar, client_id=_cli.client_id,
                        scope="openid",
                        opponent_id=_cli.provider_info["issuer"])
                    if _qresp:
                        self.trace.info("[%s]: %s" % (_qresp.type(),
                                                      _qresp.to_dict()))
                        if _qresp.extra():
                            self.trace.info(
                                "### extra claims: %s" % _qresp.extra())
                        self.response_message = _qresp
                        self.protocol_response.append((_qresp, self.info))
                    else:
                        self.response_message = None
                    err = None
                    _errtxt = ""
                except Exception, err:
                    _errtxt = "%s" % err
                    self.trace.error(_errtxt)
                    self.exception = _errtxt
                    self.test_output.append(
                        {"status": 4, "id": "OIDC error",
                         "message": "%s" % err})
                    raise FatalError

        if err:
            if self.accept_exception:
                if isinstance(err, self.accept_exception):
                    self.trace.info("Got expected exception: %s [%s]" % (
                        err, err.__class__.__name__))
                else:
                    raise
            else:
                raise FatalError(_errtxt)
        elif self.response_message:
            self.do_check("response-parse")

        return self.post_process(resp)

    def post_process(self, resp):
        if self.response_message:
            try:
                self.test_sequence(resp.tests["post"])
            except KeyError:
                pass

            if isinstance(self.response_message, RegistrationResponse):
                self.client.registration_response = self.response_message
                for key in ["client_id", "client_secret",
                            "registration_access_token",
                            "registration_client_uri"]:
                    try:
                        setattr(self.client, key, self.response_message[key])
                    except KeyError:
                        pass

            resp(self, self.response_message)

            return True
        else:
            return False

    def collect_extra_args(self):
        _args = {}
        for param in ["extra_args", "kwargs_mod"]:
            try:
                spec = self.extra_args[param]
            except KeyError:
                continue
            else:
                try:
                    _args = {param: spec[self.req.__class__.__name__]}
                except KeyError:
                    try:
                        _args = {param: spec[self.req.request]}
                    except KeyError:
                        pass
        return _args

    def send(self):
        try:
            self.test_sequence(self.req.tests["pre"])
        except KeyError:
            pass

        try:
            if self.verbose:
                print >> sys.stderr, "> %s" % self.req.request

            extra_args = self.collect_extra_args()
            try:
                extra_args["request_args"].update({"state": self.state})
            except KeyError:
                extra_args = {"request_args": {"state": self.state}}

            try:
                extra_args.update(self.client_config[self.creq.request])
            except KeyError:
                pass
            part = self.req(location=self.position, response=self.last_response,
                            content=self.last_content, features=self.features,
                            **extra_args)
            (self.position, self.last_response, self.last_content) = part

            try:
                if not self.test_sequence(self.req.tests["post"]):
                    self.position = None
            except KeyError as err:
                pass
        except FatalError:
            raise
        except UnSupported, err:
            self.trace.info("%s" % err)
            self.test_output.append(
                {"status": 2, "id": "Check support",
                 "name": "Verifies that a function is supported"})
            raise
        except PyoidcError as err:
            if err.message:
                self.trace.info("Protocol message: %s" % err.message)
            self.test_output.append(
                {"status": 3, "id": "OIDC error",
                 "message": "%s" % err})
            raise FatalError
        except Exception, err:
            self.err_check("exception", err)
