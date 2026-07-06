import asyncio
from src.mcp_tools import pz_get_guide

async def test_tool():
    print("Testing pz_get_guide with 'lua_debug_guide'...")
    result = pz_get_guide("lua_debug_guide")
    if "error" in result:
        print(f"FAILED: {result['error']}")
    else:
        print("SUCCESS!")
        print(f"Found ID: {result['id']}")
        print(f"Prose Preview: {result['prose'][:100]}...")

if __name__ == "__main__":
    asyncio.run(test_tool())
