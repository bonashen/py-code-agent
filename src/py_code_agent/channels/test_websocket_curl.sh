#!/bin/bash
# WebSocket Test with curl

WS_URL="ws://127.0.0.1:8080/ws"
PORT=8080

echo "=== WebSocket Channel Test ==="
echo ""
echo "1. Start WebSocket server:"
echo "   pi-code-agent ws-server --port $PORT --no-auth"
echo ""
echo "2. Test with curl (requires wscat or similar):"
echo "   npm install -g wscat"
echo "   wscat -c $WS_URL"
echo ""
echo "3. Or use curl with websocket:"
echo "   curl -i -N \\
        -H \"Connection: Upgrade\" \\
        -H \"Upgrade: websocket\" \\
        -H \"Sec-WebSocket-Version: 13\" \\
        -H \"Sec-WebSocket-Key: $(openssl rand -base64 16)\" \\
        http://127.0.0.1:$PORT/ws"
echo ""
echo "4. Python client (no extra deps):"
echo "   python3 -c \""
echo "import asyncio"
echo "import json"
echo "import websockets"
echo "async def test():"
echo "    async with websockets.connect('$WS_URL') as ws:"
echo "        await ws.send(json.dumps({'type': 'message', 'content': 'hello'}))"
echo "        print(await asyncio.wait_for(ws.recv(), timeout=5))"
echo "asyncio.run(test())"
echo "\""
echo ""
echo "5. JavaScript one-liner (Node.js):"
echo "   node -e \""
echo "require('ws').default = require('ws');"
echo "const ws = new (require('ws'))('$WS_URL');"
echo "ws.on('open', () => ws.send(JSON.stringify({type: 'message', content: 'hello'})));"
echo "ws.on('message', d => console.log(d.toString()));"
echo "\""
echo ""
echo "6. Send auth + message sequence:"
echo "   # Auth"
echo "   echo '{\"type\": \"auth\", \"api_key\": \"test123\", \"user_id\": \"curl_user\"}' | wscat -c $WS_URL"
echo "   # Message"
echo "   echo '{\"type\": \"message\", \"content\": \"Hello!\", \"session_id\": \"SESSION_ID\"}' | wscat -c $WS_URL"
