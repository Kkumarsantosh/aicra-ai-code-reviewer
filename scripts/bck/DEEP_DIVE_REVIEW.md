I will read the `sonar_report.json` file to identify the issues that need to be fixed.
I will use a Python script to extract and sort the issues from `sonar_report.json` by severity, filtering out any generated `.gen.go` files.
I will use `cli_help` to inquire about the availability of the `run_shell_command` tool.
I'll use the `generalist` tool to parse the `sonar_report.json` file and provide a list of the top 10 issues, sorted by severity (BLOCKER, CRITICAL, MAJOR, MINOR) and excluding `.gen.go` files.
I'll use the `codebase_investigator` tool to examine the codebase and the `sonar_report.json` file, focusing on identifying the top 10 SonarQube issues by severity while excluding any `.gen.go` files.
