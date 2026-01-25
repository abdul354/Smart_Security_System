
import sys
import traceback

print(f"Python: {sys.version}")
print(f"Executable: {sys.executable}")

try:
    import mediapipe as mp
    print(f"MediaPipe File: {mp.__file__}")
    
    # Try importing solutions directly to see the REAL error
    try:
        from mediapipe.python import solutions
        print("Successfully imported mediapipe.python.solutions")
    except ImportError as e:
        print(f"\nCRITICAL: Failed to import solutions directly.\nError: {e}")
        traceback.print_exc()
        
    try:
        print(f"Solutions dir: {dir(mp.solutions)}")
    except AttributeError:
        print("\nmp.solutions is missing (AttributeError)")

except Exception as e:
    print(f"\nTop-level import failed: {e}")
    traceback.print_exc()
