import subprocess
import sys

def run():
    # Capture all arguments passed to docker (e.g., --pg-host, --pg-user)
    args = sys.argv[1:]


    # Run unit tests first
    tests = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "unit_tests"]
    )

    if tests.returncode != 0:
        print("Unit tests failed. Pipeline stopped.")
        sys.exit(tests.returncode)
    # Define the scripts you want to run in order
    scripts = ["src/a_ingest_data.py", "src/b_silver_layer.py", "src/c_gold_layer.py"]
    
    for script in scripts:
        print(f" \n >>> Starting execution of: {script} \n")
        
        # sys.executable ensures we use the UV-managed Python environment
        result = subprocess.run([sys.executable, script] + args)
        
        # If a script fails, stop the whole process
        if result.returncode != 0:
            print(f"Error: {script} failed with exit code {result.returncode}")
            sys.exit(result.returncode)

    print("\n Pipeline run completed successfully! \n")

if __name__ == "__main__":
    run()