#!/usr/bin/env python3
"""WebSocket test client for channel testing."""
import asyncio
import json
import sys
import argparse


async def main():
    parser = argparse.ArgumentParser(description="WebSocket test client")
    parser.add_argument("--url", default="ws://127.0.0.1:8080/ws", help="WebSocket URL")
    parser.add_argument("--api-key", help="API key for authentication")
    parser.add_argument("--user-id", default="test_user", help="User ID")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    args = parser.parse_args()
    
    try:
        import websockets
    except ImportError:
        print("Error: websockets package required. Install with: pip install websockets")
        sys.exit(1)
    
    try:
        async with websockets.connect(args.url) as ws:
            print(f"Connected to {args.url}")
            
            if args.api_key:
                auth_msg = {
                    "type": "auth",
                    "api_key": args.api_key,
                    "user_id": args.user_id
                }
                await ws.send(json.dumps(auth_msg))
                response = await ws.recv()
                auth_resp = json.loads(response)
                
                if auth_resp.get("success"):
                    print(f"Authenticated! Session: {auth_resp.get('session_id')}")
                    session_id = auth_resp.get("session_id")
                else:
                    print(f"Auth failed: {auth_resp.get('error')}")
                    return
            else:
                session_id = None
            
            if args.interactive:
                print("\nInteractive mode. Type 'exit' to quit.")
                print("-" * 40)
                
                async def send_loop():
                    while True:
                        try:
                            user_input = input("\nYou: ")
                            if user_input.lower() in ("exit", "quit", "q"):
                                break
                            
                            msg = {
                                "type": "message",
                                "content": user_input,
                                "user_id": args.user_id
                            }
                            if session_id:
                                msg["session_id"] = session_id
                            
                            await ws.send(json.dumps(msg))
                        except EOFError:
                            break
                        except Exception as e:
                            print(f"Error: {e}")
                            break
                
                async def recv_loop():
                    try:
                        while True:
                            response = await ws.recv()
                            data = json.loads(response)
                            
                            if data.get("type") == "auth_response":
                                continue
                            
                            print(f"\nAssistant: {data.get('content', '')}")
                    except websockets.exceptions.ConnectionClosed:
                        print("\nConnection closed")
                
                await asyncio.gather(send_loop(), recv_loop())
            else:
                test_messages = [
                    "Hello, this is a test message",
                    "What is Python?",
                    "List files in current directory"
                ]
                
                for msg_content in test_messages:
                    msg = {
                        "type": "message",
                        "content": msg_content,
                        "user_id": args.user_id
                    }
                    if session_id:
                        msg["session_id"] = session_id
                    
                    print(f"\nSending: {msg_content}")
                    await ws.send(json.dumps(msg))
                    
                    try:
                        response = await asyncio.wait_for(ws.recv(), timeout=10.0)
                        data = json.loads(response)
                        print(f"Received: {data.get('content', '')}")
                    except asyncio.TimeoutError:
                        print("Timeout waiting for response")
                
                print("\nTest completed!")
    
    except websockets.exceptions.ConnectionRefusedError:
        print(f"Error: Connection refused - is the server running at {args.url}?")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
