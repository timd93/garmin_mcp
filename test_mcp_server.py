"""
Test script for MCP server functionality
This script tests the MCP server directly without needing Claude Desktop
"""

import asyncio
import sys
import json

sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from dotenv import load_dotenv

# Import MCP client for testing
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Load environment variables
load_dotenv()


async def test_mcp_server():
    """Test MCP server by simulating a client connection"""
    # Path to the server script
    server_script = Path(__file__).parent / "src" / "garmin_mcp" / "__init__.py"

    if not server_script.exists():
        print(f"ERROR: Server script not found at {server_script}")
        return

    print(f"Testing MCP server at: {server_script}")

    # Create server parameters
    import os
    env = os.environ.copy()
    env["GARMIN_MCP_TRANSPORT"] = "stdio"
    env["GARMIN_MCP_TEST_MODE"] = "true"

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(server_script)],
        env=env,
    )

    try:
        # Connect to server
        print("Connecting to MCP server...")
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # Initialize the connection
                print("Initializing connection...")
                await session.initialize()

                # List available tools
                print("\nListing available tools:")
                tools = await session.list_tools()
                for tool in tools.tools:
                    print(f"  - {tool.name}: {tool.description}")

                # Test each tool with sample parameters
                print("\nTesting tools:")

                # Test list_activities
                print("\nTesting list_activities...")
                try:
                    result = await session.call_tool(
                        "list_activities", arguments={"limit": 2}
                    )
                    print(f"Result: {result.content[0].text[:500]}...")
                except Exception as e:
                    print(f"ERROR: {str(e)}")

                # Test get_steps_data
                print("\nTesting get_steps_data...")
                try:
                    result = await session.call_tool(
                        "get_steps_data", arguments={"date": "2026-06-05"}
                    )
                    print(f"Result: {result.content[0].text[:500]}...")
                except Exception as e:
                    print(f"ERROR: {str(e)}")

                print("\nMCP server test completed")

    except Exception as e:
        print(f"ERROR: Failed to connect to MCP server: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_mcp_server())
