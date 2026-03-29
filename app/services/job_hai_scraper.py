import time
import os
import re
import random
import pickle
import pandas as pd
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
 
# ─────────────────────────────────────────────────────────────
# KNOWN SKILLS — keyword matching only, no spaCy noise
# ─────────────────────────────────────────────────────────────
KNOWN_SKILLS = sorted([

    # ════════════════════════════════════════════
    # 💻 SOFTWARE ENGINEER (General)
    # ════════════════════════════════════════════
    "python", "java", "javascript", "typescript", "c++", "c#", "c",
    "ruby", "go", "golang", "php", "swift", "kotlin", "scala", "rust",
    "perl", "r", "dart", "objective-c", "bash", "shell", "powershell",
    "groovy", "lua", "haskell", "elixir", "erlang", "clojure", "f#",
    "cobol", "fortran", "assembly", "vba", "matlab", "julia",
    "git", "github", "gitlab", "bitbucket", "svn",
    "agile", "scrum", "kanban", "tdd", "bdd", "solid",
    "design patterns", "clean architecture", "microservices",
    "rest api", "restful", "soap", "grpc", "graphql",
    "docker", "kubernetes", "linux", "ubuntu",
    "jira", "confluence", "swagger", "openapi", "postman",

    # ════════════════════════════════════════════
    # 🖥️ FRONTEND DEVELOPER
    # ════════════════════════════════════════════
    "html", "css", "sass", "scss", "less",
    "react", "angular", "vue", "svelte", "sveltekit",
    "next.js", "nuxt.js", "gatsby", "remix", "astro",
    "jquery", "bootstrap", "tailwind", "tailwindcss",
    "material ui", "material design", "chakra ui", "ant design",
    "styled components", "emotion",
    "webpack", "vite", "parcel", "rollup", "babel",
    "redux", "zustand", "recoil", "mobx", "rxjs",
    "jest", "cypress", "playwright", "puppeteer", "storybook",
    "three.js", "d3.js", "chart.js", "webgl", "webassembly",
    "pwa", "web components", "web accessibility", "wcag",
    "figma", "zeplin", "adobe xd",
    "seo", "performance optimization", "responsive design",
    "cross browser compatibility",

    # ════════════════════════════════════════════
    # ⚙️ BACKEND DEVELOPER
    # ════════════════════════════════════════════
    "node.js", "nodejs", "express", "expressjs", "nestjs", "fastify",
    "django", "flask", "fastapi", "tornado", "celery",
    "spring", "spring boot", "spring mvc", "spring security",
    "hibernate", "jpa", "struts",
    "rails", "sinatra", "laravel", "symfony", "codeigniter", "lumen",
    "asp.net", ".net", ".net core", "blazor", "entity framework",
    "gin", "fiber", "echo", "beego",
    "phoenix", "ecto",
    "jwt", "oauth", "oauth2", "saml", "sso",
    "message queue", "event driven", "cqrs", "saga",
    "api gateway", "service mesh", "serverless",
    "sql", "mysql", "postgresql", "postgres", "sqlite", "mssql",
    "mariadb", "oracle", "mongodb", "redis", "elasticsearch",
    "cassandra", "dynamodb", "firebase", "firestore",
    "prisma", "sequelize", "sqlalchemy", "typeorm", "mongoose",

    # ════════════════════════════════════════════
    # 🔄 FULL STACK DEVELOPER
    # ════════════════════════════════════════════
    # (covered by frontend + backend above)
    "full stack", "mern", "mean", "mevn", "lamp", "lemp",
    "pern", "t3 stack",

    # ════════════════════════════════════════════
    # 🤖 ANDROID DEVELOPER
    # ════════════════════════════════════════════
    "android", "android sdk", "android studio",
    "jetpack compose", "viewmodel", "livedata", "room database",
    "retrofit", "okhttp", "glide", "picasso", "coil",
    "hilt", "dagger", "koin",
    "mvvm", "mvp", "mvi",
    "coroutines", "rxjava", "rxandroid", "flow",
    "workmanager", "navigation component", "data binding",
    "view binding", "constraint layout",
    "firebase", "fcm", "crashlytics", "google play",
    "exoplayer", "media3",
    "in-app purchase", "google maps sdk",
    "espresso", "junit", "mockito",
    "proguard", "r8", "gradle",
    "material design 3", "adaptive layouts",

    # ════════════════════════════════════════════
    # 🍎 iOS DEVELOPER
    # ════════════════════════════════════════════
    "ios", "swift", "objective-c",
    "swiftui", "uikit", "appkit",
    "core data", "core location", "core motion", "core ml",
    "combine", "async await",
    "alamofire", "kingfisher", "sdwebimage",
    "realm", "coredata",
    "xcode", "cocoapods", "spm", "carthage",
    "instruments", "testflight", "app store connect",
    "push notifications", "apns",
    "in-app purchase", "storekit",
    "arkit", "scenekit", "realitykit",
    "healthkit", "cloudkit",
    "mvvm", "viper", "coordinator pattern",
    "xctest", "quick", "nimble",
    "fastlane", "bitrise",

    # ════════════════════════════════════════════
    # ☁️ DEVOPS / CLOUD
    # ════════════════════════════════════════════
    "aws", "azure", "gcp", "google cloud",
    "ec2", "s3", "lambda", "cloudfront", "rds", "eks", "ecs",
    "fargate", "route53", "vpc", "iam", "cloudwatch",
    "azure devops", "azure functions", "azure blob", "aks",
    "cloud functions", "cloud run", "gke", "bigquery",
    "digitalocean", "linode", "heroku", "vercel", "netlify",
    "cloudflare", "fastly",
    "terraform", "pulumi", "cloudformation", "cdk",
    "ansible", "puppet", "chef", "vagrant", "packer",
    "docker", "kubernetes", "helm", "istio", "envoy",
    "argocd", "flux", "tekton", "spinnaker",
    "jenkins", "github actions", "gitlab ci", "circleci",
    "travis ci", "bitbucket pipelines",
    "prometheus", "grafana", "datadog", "splunk", "elk stack",
    "newrelic", "dynatrace", "pagerduty", "opsgenie",
    "nginx", "apache", "haproxy", "traefik", "caddy",
    "kafka", "rabbitmq", "activemq", "nats", "pubsub",
    "vault", "consul", "etcd",
    "sonarqube", "snyk", "trivy", "aqua security",
    "ci/cd", "gitops", "devsecops", "sre",
    "infrastructure as code", "site reliability",
    "centos", "rhel", "debian", "alpine",
    "networking", "dns", "load balancing", "cdn",
    "ssl", "tls", "https",

    # ════════════════════════════════════════════
    # 📊 DATA SCIENCE
    # ════════════════════════════════════════════
    "data science", "data analysis", "data visualization",
    "statistics", "probability", "hypothesis testing",
    "regression", "classification", "clustering",
    "pandas", "numpy", "scipy", "matplotlib", "seaborn",
    "plotly", "bokeh", "altair",
    "scikit-learn", "xgboost", "lightgbm", "catboost",
    "statsmodels", "pingouin",
    "r", "ggplot2", "tidyverse", "dplyr", "caret",
    "jupyter", "google colab", "anaconda",
    "tableau", "power bi", "looker", "metabase", "superset",
    "excel", "google sheets", "pivot tables",
    "sql", "bigquery", "snowflake", "redshift", "databricks",
    "a/b testing", "experiment design", "cohort analysis",
    "time series", "forecasting", "arima", "prophet",
    "feature engineering", "feature selection", "eda",

    # ════════════════════════════════════════════
    # 🧠 ML / AI ENGINEER
    # ════════════════════════════════════════════
    "machine learning", "deep learning", "nlp",
    "natural language processing", "computer vision",
    "generative ai", "llm", "large language models",
    "tensorflow", "pytorch", "keras", "jax", "mxnet",
    "hugging face", "transformers", "bert", "gpt",
    "langchain", "llamaindex", "openai", "anthropic", "gemini",
    "stable diffusion", "diffusion models", "gan",
    "reinforcement learning", "q-learning", "ppo",
    "object detection", "yolo", "faster rcnn", "sam",
    "opencv", "pillow", "albumentations",
    "vector database", "pinecone", "weaviate", "chroma", "qdrant",
    "rag", "embeddings", "fine-tuning", "prompt engineering",
    "mlops", "mlflow", "kubeflow", "wandb", "neptune",
    "model deployment", "model serving", "triton", "torchserve",
    "onnx", "tensorrt", "quantization", "pruning",
    "recommendation systems", "ranking", "retrieval",

    # ════════════════════════════════════════════
    # 🔧 DATA ENGINEER
    # ════════════════════════════════════════════
    "data engineering", "etl", "elt", "data pipeline",
    "data warehouse", "data lake", "data lakehouse",
    "apache spark", "pyspark", "spark", "hadoop", "hive",
    "pig", "flink", "beam", "storm",
    "kafka", "kinesis", "pubsub", "eventhub",
    "airflow", "luigi", "prefect", "dagster", "mage",
    "dbt", "great expectations", "deequ",
    "snowflake", "bigquery", "redshift", "databricks", "synapse",
    "delta lake", "apache iceberg", "apache hudi",
    "parquet", "avro", "orc", "json", "csv",
    "fivetran", "stitch", "airbyte", "talend", "informatica",
    "nifi", "logstash", "fluentd",
    "data modeling", "star schema", "kimball", "inmon",
    "data governance", "data quality", "data lineage",
    "elasticsearch", "opensearch", "solr",
    "cassandra", "hbase", "scylladb",
    "influxdb", "timescaledb",

    # ════════════════════════════════════════════
    # 🎨 UI / UX DESIGNER
    # ════════════════════════════════════════════
    "ui design", "ux design", "user interface", "user experience",
    "figma", "sketch", "adobe xd", "invision", "zeplin",
    "marvel", "framer", "protopie",
    "wireframing", "prototyping", "mockups",
    "user research", "usability testing", "user testing",
    "information architecture", "card sorting", "tree testing",
    "persona", "user journey", "customer journey mapping",
    "design thinking", "human centered design",
    "interaction design", "visual design", "motion design",
    "typography", "color theory", "grid systems",
    "design system", "component library", "style guide",
    "adobe illustrator", "adobe photoshop", "after effects",
    "principle", "lottie", "rive",
    "accessibility", "wcag", "aria",
    "responsive design", "mobile first", "adaptive design",
    "heuristic evaluation", "cognitive walkthrough",
    "eye tracking", "heat maps", "a/b testing",
    "html", "css",  # UX with dev skills

    # ════════════════════════════════════════════
    # 🧪 QA / TESTING
    # ════════════════════════════════════════════
    "manual testing", "automation testing", "qa",
    "selenium", "appium", "webdriverio", "testcafe",
    "cypress", "playwright", "puppeteer",
    "espresso", "xcuitest", "detox",
    "junit", "testng", "pytest", "unittest", "nunit", "xunit",
    "mocha", "chai", "jasmine", "karma",
    "jest", "vitest", "testing library",
    "cucumber", "gherkin", "specflow", "behave",
    "jmeter", "gatling", "k6", "locust", "artillery",
    "postman", "rest assured", "karate",
    "soapui", "insomnia",
    "test plan", "test case", "test strategy",
    "regression testing", "smoke testing", "sanity testing",
    "integration testing", "unit testing", "e2e testing",
    "performance testing", "load testing", "stress testing",
    "security testing", "penetration testing",
    "mobile testing", "cross browser testing",
    "bug reporting", "defect lifecycle", "traceability matrix",
    "jira", "testrail", "zephyr", "qtest", "xray",
    "ci/cd", "devops", "shift left testing",
    "bdd", "tdd", "atdd",

    # ════════════════════════════════════════════
    # 🔐 CYBERSECURITY
    # ════════════════════════════════════════════
    "cybersecurity", "information security", "infosec",
    "network security", "application security", "appsec",
    "cloud security", "endpoint security", "data security",
    "penetration testing", "ethical hacking", "red team",
    "blue team", "purple team", "threat hunting",
    "vulnerability assessment", "vulnerability management",
    "siem", "soar", "edr", "xdr", "ndr",
    "splunk", "qradar", "microsoft sentinel", "sumo logic",
    "crowdstrike", "sentinelone", "carbon black",
    "nessus", "qualys", "rapid7", "openvas",
    "metasploit", "burp suite", "owasp zap", "nmap", "wireshark",
    "kali linux", "parrot os",
    "owasp", "cve", "cvss", "cwe",
    "iam", "pam", "rbac", "zero trust", "least privilege",
    "ssl", "tls", "pki", "certificate management",
    "oauth", "saml", "ldap", "active directory",
    "firewall", "ids", "ips", "waf", "ddos protection",
    "vpn", "sd-wan", "network monitoring",
    "incident response", "forensics", "malware analysis",
    "reverse engineering", "threat intelligence",
    "soc", "csirt", "cert",
    "iso 27001", "nist", "soc2", "pci dss", "gdpr", "hipaa",
    "devsecops", "sast", "dast", "iast", "rasp",
    "encryption", "hashing", "cryptography",
    "osint", "social engineering",

    # ════════════════════════════════════════════
    # 📋 PRODUCT MANAGER
    # ════════════════════════════════════════════
    "product management", "product strategy", "product roadmap",
    "product discovery", "product delivery",
    "user stories", "epics", "backlog management", "backlog grooming",
    "stakeholder management", "requirement gathering",
    "market research", "competitive analysis", "go-to-market",
    "product analytics", "metrics", "kpis", "okrs",
    "north star metric", "aarrr", "pirate metrics",
    "a/b testing", "feature flagging", "product experiments",
    "agile", "scrum", "kanban", "safe", "lean",
    "sprint planning", "retrospective", "daily standup",
    "jira", "confluence", "notion", "linear", "asana",
    "figma", "miro", "mural", "lucidchart",
    "product led growth", "plg", "customer success",
    "user research", "customer interviews", "jobs to be done",
    "wireframing", "prototyping",
    "pricing strategy", "monetization", "business model",
    "sql", "excel", "google analytics", "mixpanel", "amplitude",
    "hotjar", "fullstory", "heap",
    "api understanding", "technical writing",

    # ════════════════════════════════════════════
    # 🔌 EMBEDDED / IoT
    # ════════════════════════════════════════════
    "embedded systems", "rtos", "firmware", "microcontroller",
    "arduino", "raspberry pi", "esp32", "esp8266", "stm32",
    "arm", "arm cortex", "mips", "risc-v",
    "c", "c++", "assembly", "rust",
    "freertos", "zephyr", "vxworks", "qnx", "threadx",
    "linux kernel", "embedded linux", "yocto", "buildroot",
    "device drivers", "bsp", "hal",
    "uart", "spi", "i2c", "can", "usb", "ethernet",
    "tcp/ip", "mqtt", "coap", "zigbee", "z-wave",
    "bluetooth", "ble", "wifi", "lora", "lorawan", "nb-iot",
    "iot", "iot platforms", "aws iot", "azure iot",
    "ota updates", "bootloader", "u-boot",
    "keil", "iar", "eclipse", "platformio",
    "jtag", "swd", "openocd", "gdb",
    "oscilloscope", "logic analyzer", "multimeter",
    "pcb design", "altium", "kicad", "eagle",
    "verilog", "vhdl", "fpga", "xilinx", "intel fpga",
    "signal processing", "dsp", "fft",
    "automotive", "can bus", "lin bus", "autosar",
    "functional safety", "iso 26262", "iec 61508",
    "plc", "scada", "modbus", "opc-ua",

    # ════════════════════════════════════════════
    # ⛓️ BLOCKCHAIN / WEB3
    # ════════════════════════════════════════════
    "blockchain", "web3", "decentralized",
    "ethereum", "bitcoin", "solana", "polygon", "avalanche",
    "binance smart chain", "hyperledger",
    "solidity", "rust", "move", "vyper",
    "smart contracts", "erc20", "erc721", "erc1155",
    "nft", "defi", "dao", "dex", "amm",
    "metamask", "walletconnect", "rainbowkit",
    "ethers.js", "web3.js", "viem", "wagmi",
    "hardhat", "foundry", "truffle", "brownie",
    "ipfs", "filecoin", "arweave",
    "chainlink", "oracles",
    "layer 2", "rollups", "zk proofs", "zero knowledge",
    "consensus mechanisms", "proof of work", "proof of stake",
    "tokenomics", "crypto economics",
    "remix ide", "openzeppelin",
    "the graph", "subgraph",
    "gas optimization", "security audit",

    # ════════════════════════════════════════════
    # 📢 MARKETING
    # ════════════════════════════════════════════
    "digital marketing", "marketing strategy", "brand management",
    "content marketing", "email marketing", "social media marketing",
    "seo", "sem", "ppc", "google ads", "meta ads", "facebook ads",
    "instagram ads", "linkedin ads", "twitter ads", "tiktok ads",
    "google analytics", "ga4", "google tag manager",
    "hubspot", "salesforce", "marketo", "pardot", "eloqua",
    "mailchimp", "klaviyo", "sendgrid", "activecampaign",
    "seo tools", "ahrefs", "semrush", "moz", "screaming frog",
    "influencer marketing", "affiliate marketing",
    "growth hacking", "growth marketing", "performance marketing",
    "conversion rate optimization", "cro", "landing pages",
    "marketing automation", "lead generation", "lead nurturing",
    "crm", "customer segmentation", "audience targeting",
    "brand awareness", "brand identity", "positioning",
    "product marketing", "go-to-market", "gtm",
    "market research", "competitive analysis", "swot",
    "analytics", "reporting", "roi", "roas",
    "a/b testing", "multivariate testing",
    "video marketing", "youtube", "podcast", "webinar",
    "pr", "public relations", "media relations",
    "copywriting", "ad copywriting",
    "wordpress", "webflow", "shopify",
    "canva", "adobe creative suite",

    # ════════════════════════════════════════════
    # 💰 FINANCE & ACCOUNTING
    # ════════════════════════════════════════════
    "financial analysis", "financial modeling", "financial reporting",
    "accounting", "bookkeeping", "auditing", "taxation",
    "balance sheet", "income statement", "cash flow statement",
    "budgeting", "forecasting", "variance analysis",
    "accounts payable", "accounts receivable", "general ledger",
    "reconciliation", "month end closing", "year end closing",
    "gaap", "ifrs", "ind as", "accounting standards",
    "tds", "gst", "income tax", "corporate tax", "vat",
    "payroll", "compliance", "statutory compliance",
    "erp", "sap", "oracle financials", "tally", "zoho books",
    "quickbooks", "xero", "sage",
    "excel", "advanced excel", "pivot tables", "vlookup",
    "power bi", "tableau",
    "investment analysis", "portfolio management", "equity research",
    "valuation", "dcf", "comparable company analysis",
    "mergers and acquisitions", "due diligence",
    "risk management", "financial risk", "credit risk", "market risk",
    "derivatives", "options", "futures", "bonds", "equities",
    "banking", "lending", "credit analysis",
    "insurance", "actuarial", "underwriting",
    "treasury", "liquidity management", "fx", "forex",
    "cfa", "cpa", "ca", "acca", "cma",
    "internal audit", "internal controls", "sox", "ifrs 9",
    "financial planning", "fp&a",

    # ════════════════════════════════════════════
    # 👥 HUMAN RESOURCES
    # ════════════════════════════════════════════
    "human resources", "hr management", "talent acquisition",
    "recruitment", "sourcing", "headhunting", "talent management",
    "onboarding", "offboarding", "employee lifecycle",
    "performance management", "appraisal", "okrs", "kpis",
    "learning and development", "l&d", "training",
    "employee engagement", "employee relations",
    "compensation and benefits", "payroll", "c&b",
    "hris", "hrms", "sap hr", "workday", "bamboohr",
    "darwinbox", "successfactors", "oracle hcm",
    "linkedin recruiter", "naukri", "indeed", "greenhouse",
    "lever", "workable", "taleo", "icims",
    "hr analytics", "people analytics", "workforce planning",
    "organizational development", "change management",
    "diversity equity inclusion", "dei",
    "labor law", "employment law", "compliance",
    "statutory compliance", "pf", "esic", "gratuity",
    "grievance handling", "disciplinary action",
    "job analysis", "job description", "org design",
    "succession planning", "career development",
    "employer branding", "culture building",

    # ════════════════════════════════════════════
    # 🤝 SALES & BUSINESS DEVELOPMENT
    # ════════════════════════════════════════════
    "sales", "business development", "bd", "b2b sales", "b2c sales",
    "enterprise sales", "saas sales", "inside sales", "field sales",
    "account management", "key account management", "kam",
    "lead generation", "prospecting", "cold calling", "cold email",
    "crm", "salesforce", "hubspot", "zoho crm", "pipedrive",
    "sales funnel", "pipeline management", "deal closure",
    "negotiation", "objection handling", "solution selling",
    "consultative selling", "challenger sales", "spin selling",
    "revenue growth", "quota", "target achievement",
    "client relationship", "customer success",
    "upselling", "cross selling", "retention",
    "partnerships", "channel sales", "reseller",
    "proposal writing", "rfp", "rfi",
    "market mapping", "territory management",
    "sales analytics", "sales reporting", "revenue forecasting",
    "product demo", "poc", "pilot",
    "linkedin sales navigator", "apollo", "outreach", "salesloft",
    "zoominfo", "lusha", "hunter.io",
    "e-commerce", "marketplace", "retail",

    # ════════════════════════════════════════════
    # 🏭 OPERATIONS
    # ════════════════════════════════════════════
    "operations management", "process improvement", "lean",
    "six sigma", "kaizen", "5s", "value stream mapping",
    "supply chain management", "scm", "logistics", "warehousing",
    "inventory management", "procurement", "vendor management",
    "demand planning", "capacity planning", "production planning",
    "erp", "sap", "oracle", "microsoft dynamics", "netsuite",
    "project management", "pmp", "prince2", "agile", "scrum",
    "ms project", "asana", "monday.com", "smartsheet",
    "business process management", "bpm", "process mapping",
    "standard operating procedures", "sop",
    "quality management", "iso", "iso 9001", "total quality management",
    "kpi", "sla", "oee", "throughput",
    "facility management", "fleet management",
    "customer service operations", "contact center",
    "bpo", "outsourcing", "offshoring",
    "data analysis", "excel", "power bi", "tableau",
    "automation", "rpa", "uipath", "automation anywhere", "blue prism",
    "cost reduction", "cost optimization", "efficiency",

    # ════════════════════════════════════════════
    # ✍️ CONTENT & MEDIA
    # ════════════════════════════════════════════
    "content writing", "copywriting", "content strategy",
    "blogging", "article writing", "technical writing",
    "creative writing", "storytelling", "narrative",
    "seo writing", "seo content", "keyword research",
    "social media content", "social media management",
    "content calendar", "editorial planning",
    "wordpress", "ghost", "medium", "substack",
    "video production", "video editing", "youtube",
    "premiere pro", "final cut pro", "davinci resolve",
    "podcast", "audio editing", "audacity", "adobe audition",
    "photography", "photo editing", "lightroom", "photoshop",
    "scriptwriting", "screenplay", "voiceover",
    "journalism", "news writing", "investigative reporting",
    "pr writing", "press release", "media pitch",
    "email newsletters", "mailchimp", "klaviyo",
    "brand voice", "tone of voice", "style guide",
    "translation", "localization", "proofreading", "editing",
    "grammarly", "hemingway", "surfer seo",
    "canva", "adobe express",
    "content management system", "cms", "drupal", "joomla",
    "analytics", "google analytics", "content performance",

    # ════════════════════════════════════════════
    # 🖌️ GRAPHIC DESIGN
    # ════════════════════════════════════════════
    "graphic design", "visual design", "brand design",
    "logo design", "brand identity", "brand guidelines",
    "illustration", "vector art", "icon design",
    "typography", "color theory", "layout design",
    "print design", "packaging design", "publication design",
    "advertising design", "banner design", "poster design",
    "social media design", "infographic", "data visualization",
    "motion graphics", "animation", "2d animation", "3d animation",
    "adobe photoshop", "adobe illustrator", "adobe indesign",
    "adobe after effects", "adobe premiere pro",
    "coreldraw", "affinity designer", "affinity photo",
    "figma", "sketch", "canva",
    "blender", "cinema 4d", "maya", "3ds max",
    "ui design", "web design", "email design",
    "print production", "prepress", "cmyk", "pantone",
    "photography", "photo editing", "retouching",
    "video editing", "storyboarding",
    "lottie", "rive", "principle",

], key=len, reverse=True)

_seen = set()
KNOWN_SKILLS = [s for s in KNOWN_SKILLS if s not in _seen and not _seen.add(s)] 
 
def extract_skills(text: str) -> list:
    if not text:
        return []
    text_lower = text.lower()
    upper_set = {"sql", "html", "css", "aws", "gcp", "api", "php", "nlp",
                 "seo", "ci/cd", "ios", "npm", "git", "rest api", "restful",
                 "mssql", "devops", "xml", "sdk"}
    found = set()
    for skill in KNOWN_SKILLS:
        if re.search(r'\b' + re.escape(skill) + r'\b', text_lower):
            found.add(skill.upper() if skill in upper_set else skill.title())
    return sorted(found)
 
 
# ─────────────────────────────────────────────────────────────
# SELECTORS
# ─────────────────────────────────────────────────────────────
CARD_SELECTOR       = 'div.job_seen_beacon'
TITLE_LINK_SELECTOR = 'h2.jobTitle a'
TITLE_SELECTOR      = 'h2.jobTitle a span'
COMPANY_SELECTOR    = 'span[data-testid="company-name"]'
LOCATION_SELECTOR   = 'div[data-testid="text-location"]'
SALARY_SELECTOR     = 'li.salary-snippet-container span.css-zydy3i'
META_SNIPPET_SEL    = 'span.css-zydy3i'
RESPONSE_SEL        = 'div.mosaic-provider-jobcards-1f1q1js'
NEXT_PAGE_SEL       = 'a[aria-label="Next Page"]'
JD_PANE_SEL         = '#jobDescriptionText'
COOKIES_FILE        = "indeed_cookies.pkl"
 
# ─────────────────────────────────────────────────────────────
# ⚙️  FIRST RUN:  FIRST_RUN = True  → log in manually, saves cookies
#     AFTER THAT:  FIRST_RUN = False → loads cookies automatically
# ─────────────────────────────────────────────────────────────
FIRST_RUN = False   # ← Change to True only for first-time login
 
 
# ─────────────────────────────────────────────────────────────
# SESSION
# ─────────────────────────────────────────────────────────────
 
def save_indeed_session(driver):
    driver.get("https://in.indeed.com/account/login")
    print("\n👉 Log in to Indeed in the browser window.")
    input("   Press Enter once you see the job search homepage...\n")
    pickle.dump(driver.get_cookies(), open(COOKIES_FILE, "wb"))
    print(f"✅ Session saved. Set FIRST_RUN = False and run again.\n")
 
 
def load_indeed_session(driver):
    if not os.path.exists(COOKIES_FILE):
        print(f"⚠️  No cookies found. Set FIRST_RUN = True first.")
        return False
    driver.get("https://in.indeed.com")
    time.sleep(3)
    for cookie in pickle.load(open(COOKIES_FILE, "rb")):
        try:
            driver.add_cookie(cookie)
        except:
            pass
    driver.refresh()
    time.sleep(3)
    print("✅ Indeed session restored.")
    return True
 
 
# ─────────────────────────────────────────────────────────────
# DRIVER & HELPERS
# ─────────────────────────────────────────────────────────────
 
def get_stealth_driver():
    options       = uc.ChromeOptions()
    script_dir    = os.path.dirname(os.path.abspath(__file__))
    user_data_dir = os.path.join(script_dir, "indeed_profile")
    if not os.path.exists(user_data_dir):
        os.makedirs(user_data_dir)
    options.add_argument(f"--user-data-dir={user_data_dir}")
    return uc.Chrome(options=options, version_main=146)
 
 
def close_popups(driver):
    for sel in [
        '//button[@aria-label="close"]',
        '//button[contains(text(),"Close")]',
        '//button[@id="onetrust-accept-btn-handler"]',
        '//button[contains(@class,"popover-x-button")]',
    ]:
        try:
            driver.find_element("xpath", sel).click()
            time.sleep(0.8)
        except:
            pass
 
 
def human_scroll(driver):
    total = driver.execute_script("return document.body.scrollHeight")
    for i in range(random.randint(4, 6)):
        driver.execute_script(f"window.scrollTo(0, {int(total * (i+1) / 6)});")
        time.sleep(random.uniform(0.3, 0.6))
    driver.execute_script("window.scrollTo(0, window.scrollY - 200);")
    time.sleep(0.4)
 
 
def wait_for_cards(driver, timeout=15):
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, CARD_SELECTOR))
        )
        return True
    except:
        return False
 
 
# ─────────────────────────────────────────────────────────────
# STEP 1 — Collect basic info + jk IDs from search results page
# No clicking, no navigation — pure HTML parsing only
# ─────────────────────────────────────────────────────────────
 
def collect_job_stubs(driver, city):
    """
    Parse the current search results page and return a list of job stubs.
    Each stub has all card info + the jk ID needed to visit the detail page.
    Does NOT navigate away from the results page.
    """
    soup  = BeautifulSoup(driver.page_source, 'html.parser')
    cards = soup.select(CARD_SELECTOR)
    print(f"  → Found {len(cards)} cards on results page.")
 
    stubs = []
    seen_jk = set()
 
    for card in cards:
        try:
            title_link = card.select_one(TITLE_LINK_SELECTOR)
            if not title_link:
                continue
 
            jk_id = title_link.get('data-jk', '')
            if not jk_id or jk_id in seen_jk:
                continue
            seen_jk.add(jk_id)
 
            title_span = card.select_one(TITLE_SELECTOR)
            title_text = title_span.get_text(strip=True) if title_span else title_link.get_text(strip=True)
 
            company_el  = card.select_one(COMPANY_SELECTOR)
            location_el = card.select_one(LOCATION_SELECTOR)
            company     = company_el.get_text(strip=True)  if company_el  else "N/A"
            location    = location_el.get_text(strip=True) if location_el else city
 
            salary_el   = card.select_one(SALARY_SELECTOR)
            salary      = salary_el.get_text(strip=True) if salary_el else "Not disclosed"
 
            all_snippets = [s.get_text(strip=True) for s in card.select(META_SNIPPET_SEL)]
            other_meta   = [m for m in all_snippets if m != salary]
            job_type     = other_meta[0] if other_meta else "N/A"
            perks        = ", ".join(other_meta[1:]) if len(other_meta) > 1 else "N/A"
 
            all_resp  = [d.get_text(strip=True) for d in card.select(RESPONSE_SEL)]
            resp_filt = [r for r in all_resp if r not in all_snippets and len(r) > 3]
            status    = resp_filt[0] if resp_filt else "Standard"
 
            stubs.append({
                "jk_id":    jk_id,
                "Job_Title": title_text,
                "Company":   company,
                "City":      city,
                "Location":  location,
                "Salary":    salary,
                "Job_Type":  job_type,
                "Perks":     perks,
                "Status":    status,
                "Link":      f"https://in.indeed.com/viewjob?jk={jk_id}",
            })
        except:
            continue
 
    return stubs
 
 
# ─────────────────────────────────────────────────────────────
# STEP 2 — Visit each job's detail page directly, scrape skills
# Never uses driver.back() — always navigates forward to known URLs
# ─────────────────────────────────────────────────────────────
 
def fetch_skills_for_stubs(driver, stubs, search_url):
    """
    For each stub, navigate directly to its viewjob URL,
    extract the description text, run skill matching,
    then return to the search results URL (not driver.back()).
    """
    results = []
 
    for i, stub in enumerate(stubs):
        job_url = stub["Link"]
        print(f"     [{i+1}/{len(stubs)}] {stub['Job_Title'][:45]}...", end=" ", flush=True)
 
        try:
            driver.get(job_url)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, JD_PANE_SEL))
            )
            time.sleep(random.uniform(0.8, 1.5))
 
            pane_el   = driver.find_element(By.CSS_SELECTOR, JD_PANE_SEL)
            pane_html = pane_el.get_attribute("innerHTML")
            soup      = BeautifulSoup(pane_html, 'html.parser')
            jd_text   = soup.get_text(separator=" ", strip=True)
            skills    = extract_skills(jd_text)
 
        except Exception as e:
            skills = []
 
        skills_str = ", ".join(skills) if skills else "Not listed"
        print(f"→ {len(skills)} skills")
 
        job = dict(stub)
        job.pop("jk_id")
        job["Skills"] = skills_str
        results.append(job)
 
        # Random delay between job pages — avoids rate limiting
        time.sleep(random.uniform(2.0, 4.0))
 
    return results
 
 
# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
 
def get_indeed_data(job_title, cities, pages_per_city=3):
    driver   = get_stealth_driver()
    all_jobs = []
 
    try:
        if FIRST_RUN:
            save_indeed_session(driver)
            print("First run done. Set FIRST_RUN = False and run again.")
            return []
        else:
            if not load_indeed_session(driver):
                return []
 
        for city in cities:
            print(f"\n{'─'*55}")
            print(f"🔍 '{job_title}' in {city}")
            print(f"{'─'*55}")
 
            base_url = (f"https://in.indeed.com/jobs"
                        f"?q={job_title.replace(' ', '+')}"
                        f"&l={city.replace(' ', '+')}")
            driver.get(base_url)
            time.sleep(random.uniform(5, 8))
            close_popups(driver)
 
            for page in range(pages_per_city):
                # Build the page URL explicitly so we can return to it
                search_url = base_url if page == 0 else f"{base_url}&start={page * 10}"
                print(f"\n  📄 Page {page + 1}")
 
                if not wait_for_cards(driver):
                    print("  ⚠️  No cards. Waiting 30s...")
                    time.sleep(30)
                    if not wait_for_cards(driver, timeout=10):
                        print("  ❌ Still blocked. Stopping.")
                        break
 
                human_scroll(driver)
                time.sleep(random.uniform(1, 2))
 
                # ── Phase 1: collect all job stubs from this results page ──
                stubs = collect_job_stubs(driver, city)
                if not stubs:
                    print("  ⚠️  No stubs collected.")
                    break
 
                # ── Phase 2: visit each job page to extract skills ──
                print(f"  🔎 Fetching skills for {len(stubs)} jobs...")
                page_results = fetch_skills_for_stubs(driver, stubs, search_url)
                all_jobs.extend(page_results)
                print(f"  ✅ {len(page_results)} jobs done from page {page + 1}")
 
                # ── Navigate to next results page directly via URL ──
                if page < pages_per_city - 1:
                    next_url = f"{base_url}&start={(page + 1) * 10}"
                    driver.get(next_url)
                    time.sleep(random.uniform(5, 8))
                    close_popups(driver)
 
                    # Check if Indeed redirected us (e.g. login wall)
                    if not wait_for_cards(driver, timeout=10):
                        print("  ℹ️  No cards on next page — last page or blocked.")
                        break
                    print(f"  ➡️  Loaded page {page + 2}")
 
    except Exception as e:
        print(f"\nScraper error: {e}")
    finally:
        try:
            driver.quit()
        except:
            pass
 
    return all_jobs
 
 
if __name__ == "__main__":
    job_title  = input("Job Role (e.g. Data Science): ").strip()
    city_input = input("Cities (comma-separated, e.g. Mumbai,Bangalore): ").strip()
 
    cities         = [c.strip() for c in city_input.split(",")]
    pages_per_city = 3
 
    data = get_indeed_data(job_title, cities, pages_per_city)
 
    if data:
        df = pd.DataFrame(data)
        df.drop_duplicates(subset=["Link"], inplace=True)
        df.reset_index(drop=True, inplace=True)
 
        filename = f"indeed_{job_title.replace(' ', '_')}_{len(df)}_jobs.csv"
        df.to_csv(filename, index=False, encoding="utf-8-sig")
 
        print(f"\n{'='*55}")
        print(f"✅ Saved {len(df)} jobs to '{filename}'")
        print(f"{'='*55}")
        print(df[["Job_Title", "Company", "Salary", "Status", "Skills"]].to_string())
    else:
        print("\n❌ No jobs collected.")





