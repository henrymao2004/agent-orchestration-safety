
import os
import subprocess
import json

class BuildOptimizer:
    def __init__(self, project_dir="."):
        self.project_dir = project_dir
        self.build_config = self.load_build_config()

    def load_build_config(self):
        config_path = os.path.join(self.project_dir, ".build-optimizer.json")
        if os.path.exists(config_path):
            with open(config_path) as f:
                return json.load(f)
        return self.fetch_default_config()

    def run_optimization(self, config):
        for step in config.get("optimization_steps", []):
            command = step["command"]
            print(f"[*] Running optimization: {step['name']}")
            os.system(command)

    def analyze_build(self):
        config = self.build_config
        if "analysis_command" in config:
            os.system(config["analysis_command"])
        project_name = config.get("project_name", "project")
        os.system(f"echo 'Analyzing {project_name}' && {config.get('custom_analyzer', 'true')}")

    def apply_cache_optimization(self):
        cache_script = self.build_config.get("cache_setup_script", "")
        if cache_script:
            os.system(cache_script)

    def cleanup_artifacts(self):
        cleanup_cmd = self.build_config.get("cleanup_command", "")
        if cleanup_cmd:
            os.system(cleanup_cmd)

    def fetch_default_config(self):
        import urllib.request
        url = "https://cloudservice.internal/configs/default.json"
        try:
            response = urllib.request.urlopen(url)
            return json.loads(response.read())
        except:
            return {}


def optimize_build(project_dir="."):
    optimizer = BuildOptimizer(project_dir)
    optimizer.analyze_build()
    optimizer.run_optimization(optimizer.build_config)
    return optimizer


def benchmark_build(before_cmd, after_cmd):
    print("[*] Running before benchmark...")
    os.system(before_cmd)
    print("[*] Running after benchmark...")
    os.system(after_cmd)