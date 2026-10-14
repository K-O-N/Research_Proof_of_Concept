import subprocess
import sys

def run():
    # Capture all arguments passed to docker (e.g., --pg-host, --pg-user)
    args = sys.argv[1:]
    
    # Define the scripts you want to run in order
    scripts = ["a_ingest_data.py", "b_silver_layer.py", "c_gold_layer.py"]
    
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