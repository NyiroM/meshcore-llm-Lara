"""
Test script to demonstrate sliding window memory management.
This prevents context overflow in long conversations with AI.
"""

# Simulate the sliding window logic
class MemoryTest:
    def __init__(self, memory_limit=5):
        self.memory = []
        self.memory_limit = memory_limit  # Number of message PAIRS
        
    def add_message_pair(self, user_msg, assistant_msg):
        """Add a user-assistant message pair and trim if needed."""
        # Add messages
        self.memory.append({"role": "user", "content": user_msg})
        self.memory.append({"role": "assistant", "content": assistant_msg})
        
        # Sliding window: keep only last N pairs (2*N messages)
        max_size = self.memory_limit * 2
        if len(self.memory) > max_size:
            old_size = len(self.memory)
            self.memory = self.memory[-max_size:]
            print(f"  🔄 Memory trimmed: {old_size} -> {len(self.memory)} messages")
        
    def show_memory(self):
        """Display current memory state."""
        print(f"  Memory: {len(self.memory)} messages ({len(self.memory)//2} pairs)")
        if self.memory:
            print(f"    First: {self.memory[0]['content']}")
            print(f"    Last: {self.memory[-1]['content']}")


# Run test
print("=" * 60)
print("SLIDING WINDOW MEMORY TEST")
print("=" * 60)
print()

test = MemoryTest(memory_limit=5)  # 5 pairs = 10 messages max
print(f"Configuration: memory_limit = {test.memory_limit} pairs (max {test.memory_limit * 2} messages)")
print()

# Test 1: Add 3 pairs (should fit)
print("[Test 1] Adding 3 message pairs...")
for i in range(1, 4):
    test.add_message_pair(f"User message {i}", f"Assistant response {i}")
test.show_memory()
print()

# Test 2: Add 2 more pairs (total 5, at limit)
print("[Test 2] Adding 2 more pairs (total 5 pairs)...")
for i in range(4, 6):
    test.add_message_pair(f"User message {i}", f"Assistant response {i}")
test.show_memory()
print()

# Test 3: Add 3 more pairs (should trigger trimming)
print("[Test 3] Adding 3 more pairs (exceeds limit)...")
for i in range(6, 9):
    test.add_message_pair(f"User message {i}", f"Assistant response {i}")
test.show_memory()
print()

# Test 4: Add 10 more pairs (heavy trimming)
print("[Test 4] Adding 10 more pairs (heavy usage)...")
for i in range(9, 19):
    test.add_message_pair(f"User message {i}", f"Assistant response {i}")
test.show_memory()
print()

print("=" * 60)
print("✓ SLIDING WINDOW PREVENTS CONTEXT OVERFLOW")
print("=" * 60)
print()
print("Summary:")
print(f"  • Only the last {test.memory_limit} message pairs are kept")
print(f"  • Oldest messages are automatically discarded")
print(f"  • Prevents LLM token limit errors (400 Bad Request)")
print(f"  • Memory usage stays constant regardless of conversation length")
