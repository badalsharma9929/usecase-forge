import subprocess
import sys
import os

def run_agents():
    
    python_executable = sys.executable

    
    urls = [    
        "https://byjus.com/"      
        ]

    
    
    agents_folder = os.path.join("agents")

    
    for url in urls:
        
        print(f"Running Agent 1 (Web Scraper) for URL: {url}")
        subprocess.run([python_executable, os.path.join(agents_folder, "agent1_webscrap.py"), url], check=True)
        
        
        print("Running Agent 2 (Use Case Generator)...")
        subprocess.run([python_executable, os.path.join(agents_folder, "agent2_usecase.py")], check=True)
        
        
        print("Running Agent 3 (Resource Collector)...")
        subprocess.run([python_executable, os.path.join(agents_folder, "agent3_resources.py")], check=True)

        

    print("All agents executed.👍")

if __name__ == "__main__":
    run_agents()
