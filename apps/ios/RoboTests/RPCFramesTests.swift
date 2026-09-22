// RPCFramesTests.swift — wire-contract tests for the gateway client.
// These pin the exact JSON-RPC shapes the Robo gateway (tui_gateway) emits and
// accepts; tests/tui_gateway/test_ios_client_contract.py pins the same shapes
// on the Python side so the two cannot drift silently.
import XCTest
@testable import Robo

final class RPCFramesTests: XCTestCase {
    func testRequestEnvelope() throws {
        let data = try RPCFrames.request(id: 7, method: "prompt.submit", params: ["session_id": "abc", "text": "hi"])
        let obj = try XCTUnwrap(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(obj["jsonrpc"] as? String, "2.0")
        XCTAssertEqual(obj["id"] as? Int, 7)
        XCTAssertEqual(obj["method"] as? String, "prompt.submit")
        XCTAssertEqual((obj["params"] as? [String: Any])?["text"] as? String, "hi")
    }

    func testResponseAndErrorParsing() {
        let ok = Data(#"{"jsonrpc":"2.0","id":3,"result":{"session_id":"s1"}}"#.utf8)
        guard case .response(let id, let result, let error)? = RPCFrames.parse(ok) else { return XCTFail("not a response") }
        XCTAssertEqual(id, 3); XCTAssertNil(error); XCTAssertEqual(result?["session_id"] as? String, "s1")

        let err = Data(#"{"jsonrpc":"2.0","id":4,"error":{"code":4004,"message":"no such session"}}"#.utf8)
        guard case .response(_, _, let e)? = RPCFrames.parse(err) else { return XCTFail("not a response") }
        XCTAssertEqual(e?.code, 4004)
    }

    func testEventParsing() {
        let delta = Data(#"{"jsonrpc":"2.0","method":"event","params":{"type":"message.delta","session_id":"s1","payload":{"text":"Hel"}}}"#.utf8)
        XCTAssertEqual(RPCFrames.parse(delta), .event(.messageDelta(session: "s1", text: "Hel")))

        let approval = Data(#"{"jsonrpc":"2.0","method":"event","params":{"type":"approval.request","session_id":"s1","payload":{"command":"rm -rf build","description":"recursive delete","pattern_keys":["recursive delete"]}}}"#.utf8)
        guard case .event(.approvalRequest(_, let req))? = RPCFrames.parse(approval) else { return XCTFail("not an approval") }
        XCTAssertEqual(req.command, "rm -rf build")
        XCTAssertEqual(req.patternKeys, ["recursive delete"])

        let done = Data(#"{"jsonrpc":"2.0","method":"event","params":{"type":"message.complete","session_id":"s1","payload":{"text":"Done.","status":"ok"}}}"#.utf8)
        XCTAssertEqual(RPCFrames.parse(done), .event(.messageComplete(session: "s1", text: "Done.", status: "ok")))
    }

    func testPairingStringParsing() {
        let ep = GatewayEndpoint.fromPairingString("robo://pair?url=https://robo.example.com:8642&token=abc123")
        XCTAssertEqual(ep?.baseURL.absoluteString, "https://robo.example.com:8642")
        XCTAssertEqual(ep?.accessToken, "abc123")
        XCTAssertEqual(ep?.wsScheme, "wss")
        XCTAssertNil(GatewayEndpoint.fromPairingString("https://not-a-pairing-string"))
    }
}
