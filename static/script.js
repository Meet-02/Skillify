document.addEventListener('DOMContentLoaded', () => {
    const puzzleContainer = document.querySelector('.puzzle-container');
    const puzzleScene = document.querySelector('.puzzle-scene');

    // Scroll Interaction: Snap pieces together
    window.addEventListener('scroll', () => {
        const scrollY = window.scrollY;
        // Threshold to snap
        if (scrollY > 50) {
            puzzleContainer.classList.add('puzzle-solved');
        } else {
            puzzleContainer.classList.remove('puzzle-solved');
        }

        // Slight rotation on scroll
        if (puzzleScene) {
            puzzleScene.style.transform = `rotateX(${-15 + scrollY * 0.05}deg) rotateY(${25 + scrollY * 0.1}deg)`;
        }
    });

    // Mouse Interaction: Tilt Scene
    if (puzzleContainer && puzzleScene) {
        puzzleContainer.addEventListener('mousemove', (e) => {
            const rect = puzzleContainer.getBoundingClientRect();
            const x = (e.clientX - rect.left) / rect.width;
            const y = (e.clientY - rect.top) / rect.height;

            // -1 to 1 range
            const mouseX = (x - 0.5) * 2;
            const mouseY = (y - 0.5) * 2;

            // Base rotation: RotateX(-15), RotateY(25)
            // Add mouse influence
            const tiltX = -15 + (-mouseY * 10);
            const tiltY = 25 + (mouseX * 10);

            puzzleScene.style.transform = `rotateX(${tiltX}deg) rotateY(${tiltY}deg)`;
        });

        puzzleContainer.addEventListener('mouseleave', () => {
            // Reset to base or let scroll take over
            const scrollY = window.scrollY;
            const baseX = -15 + scrollY * 0.05;
            const baseY = 25 + scrollY * 0.1;
            puzzleScene.style.transform = `rotateX(${baseX}deg) rotateY(${baseY}deg)`;
        });
    }
    // Resume Upload Logic
    const fileInput = document.getElementById('file-input');
    const fileName = document.getElementById('file-name');
    const selectedFileDiv = document.getElementById('selected-file');
    const uploadArea = document.getElementById('upload-area');

    if (fileInput) {
        fileInput.addEventListener('change', function (e) {
            if (this.files && this.files[0]) {
                fileName.textContent = this.files[0].name;
                selectedFileDiv.style.display = 'flex';
                uploadArea.style.borderColor = '#4f46e5';
                uploadArea.style.backgroundColor = '#f5f3ff';
            }
        });

        // Drag and drop effects
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.style.borderColor = '#4f46e5';
            uploadArea.style.backgroundColor = '#f5f3ff';
        });

        uploadArea.addEventListener('dragleave', (e) => {
            e.preventDefault();
            uploadArea.style.borderColor = '#e2e8f0';
            uploadArea.style.backgroundColor = 'transparent';
        });
    }
});

document.addEventListener('DOMContentLoaded', () => {

    // --- DOM Elements ---
    const chartContainer = document.getElementById('skillDemandChart');
    const growthListContainer = document.getElementById('fastestGrowingList');
    const tableBody = document.getElementById('skillsTableBody');

    // Stats Elements (These match the IDs you added in HTML)
    const totalSkillsEl = document.getElementById('total-skills-stat');
    const avgGrowthEl = document.getElementById('avg-growth-stat');
    const avgSalaryEl = document.getElementById('avg-salary-stat');
    const totalJobsEl = document.getElementById('total-jobs-stat');

    // --- 1. FETCH & INITIALIZE ---
    async function initDashboard() {
        const chartContainer = document.getElementById('skillDemandChart');
        if (!chartContainer) return;

        // Check cache first to prevent re-fetching on every click
        const cachedMarketData = localStorage.getItem('marketDataCache');
        if (cachedMarketData) {
            const skillsData = JSON.parse(cachedMarketData);
            renderChart(skillsData);
            renderGrowthList(skillsData);
            renderTable(skillsData);
            updateStatsCards(skillsData);
            setupFilters(skillsData);
            return;
        }

        // Otherwise, fetch fresh data
        const response = await fetch('/api/market-data');
        const rawData = await response.json();
        const skillsData = processData(rawData);
        localStorage.setItem('marketDataCache', JSON.stringify(skillsData));

        renderChart(skillsData);
        renderGrowthList(skillsData);
        renderTable(skillsData);
        updateStatsCards(skillsData);
        setupFilters(skillsData);

    } 



    // --- 2. DATA PROCESSOR ---
    function processData(apiData) {
        const maxJobs = Math.max(...apiData.map(d => d.jobs)) || 1;

        return apiData.map(item => {
            const demandScore = Math.round((item.jobs / maxJobs) * 100);

            // Convert raw salary (e.g. 140000 -> 140)
            const salaryK = Math.round(item.salary / 1000);

            // Mock Growth (Since API doesn't give history)
            const mockGrowth = Math.floor(Math.random() * 30) - 5;

            return {
                name: item.name,
                category: categorizeSkill(item.name),
                demand: demandScore,
                growth: mockGrowth,
                salary: salaryK,
                jobs: item.jobs,
                trend: mockGrowth > 0 ? 'up' : 'down'
            };
        });
    }

    // --- 3. UPDATE STATS CARDS (The Fix) ---
    function updateStatsCards(data) {
        if (!data || data.length === 0) return;

        // 1. Total Skills Tracked
        if (totalSkillsEl) totalSkillsEl.textContent = data.length;

        // 2. Avg Growth Calculation
        const totalGrowth = data.reduce((sum, item) => sum + item.growth, 0);
        const avgGrowth = Math.round(totalGrowth / data.length);

        if (avgGrowthEl) {
            const sign = avgGrowth > 0 ? '+' : '';
            avgGrowthEl.textContent = `${sign}${avgGrowth}%`;
            avgGrowthEl.style.color = avgGrowth >= 0 ? 'var(--success, green)' : 'var(--danger, red)';
        }

        // 3. Avg Salary (Filter out 0s so they don't ruin the average)
        const validSalaries = data.filter(item => item.salary > 0);
        const totalSalary = validSalaries.reduce((sum, item) => sum + item.salary, 0);
        const avgSalary = validSalaries.length ? Math.round(totalSalary / validSalaries.length) : 0;

        if (avgSalaryEl) {
            avgSalaryEl.textContent = avgSalary > 0 ? `$${avgSalary}k` : 'N/A';
        }

        // 4. Total Jobs
        const totalJobs = data.reduce((sum, item) => sum + item.jobs, 0);
        if (totalJobsEl) {
            // Format numbers (e.g., 12500 -> 12.5k)
            totalJobsEl.textContent = totalJobs > 1000
                ? `${(totalJobs / 1000).toFixed(1)}k`
                : totalJobs;
        }
    }

    // --- 4. CATEGORIZATION LOGIC ---
    function categorizeSkill(name) {
        const n = name.toLowerCase();
        if (['react', 'vue', 'angular', 'typescript', 'javascript', 'html', 'css', 'next.js'].some(k => n.includes(k))) return 'frontend';
        if (['python', 'node', 'django', 'go', 'java', 'php', 'ruby', 'c#', '.net'].some(k => n.includes(k))) return 'backend';
        if (['aws', 'azure', 'gcp', 'google cloud', 'lambda'].some(k => n.includes(k))) return 'cloud';
        if (['docker', 'kubernetes', 'jenkins', 'ci/cd', 'terraform', 'ansible'].some(k => n.includes(k))) return 'devops';
        if (['sql', 'pandas', 'spark', 'hadoop', 'tableau', 'data', 'mongodb', 'firebase', 'analytics'].some(k => n.includes(k))) return 'data';
        if (['figma', 'photoshop', 'xd', 'ui/ux', 'sketch'].some(k => n.includes(k))) return 'design';
        if (['tensorflow', 'pytorch', 'ai', 'machine learning', 'nlp'].some(k => n.includes(k))) return 'ai-ml';
        return 'systems';
    }

    // --- 5. RENDER FUNCTIONS ---
    function renderChart(data) {
        chartContainer.innerHTML = '';
        const topSkills = [...data].sort((a, b) => b.demand - a.demand).slice(0, 10);

        topSkills.forEach((skill, index) => {
            const barWrapper = document.createElement('div');
            barWrapper.className = 'bar-wrapper';
            const height = skill.demand;

            barWrapper.innerHTML = `
                <div class="bar" style="height: 0%;" data-height="${height}%"></div>
                <div class="bar-label">${skill.name}</div>
            `;
            chartContainer.appendChild(barWrapper);

            setTimeout(() => {
                const bar = barWrapper.querySelector('.bar');
                if (bar) bar.style.height = `${height}%`;
            }, 100 + (index * 50));
        });
    }

    function renderGrowthList(data) {
        growthListContainer.innerHTML = '';
        const growingSkills = [...data].sort((a, b) => b.growth - a.growth).slice(0, 4);

        growingSkills.forEach(skill => {
            const item = document.createElement('div');
            item.className = 'growth-item';
            const isPositive = skill.growth >= 0;
            const colorStyle = isPositive ? 'color:green;' : 'color:red;';
            const iconClass = isPositive ? 'fa-arrow-up' : 'fa-arrow-down';

            item.innerHTML = `
                <div class="growth-header">
                    <span class="growth-name">${skill.name}</span>
                    <span class="growth-rate" style="${colorStyle}">
                        <i class="fas ${iconClass}"></i> ${Math.abs(skill.growth)}%
                    </span>
                </div>
                <div class="growth-meta">
                    <span>${skill.jobs.toLocaleString()} jobs</span>
                    <span>${skill.salary > 0 ? '$' + skill.salary + 'k' : 'N/A'}</span>
                </div>
                <div class="progress-track">
                    <div class="progress-fill" style="width: ${Math.abs(skill.growth) * 1.5}%"></div>
                </div>
            `;
            growthListContainer.appendChild(item);
        });
    }

    function renderTable(data) {
        tableBody.innerHTML = '';
        if (data.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:20px;">No skills found.</td></tr>';
            return;
        }

        data.forEach(skill => {
            const row = document.createElement('tr');
            const catClass = `cat-${skill.category}`;
            const catName = skill.category.charAt(0).toUpperCase() + skill.category.slice(1);

            const isPositive = skill.trend === 'up';
            const growthColor = isPositive ? 'green' : 'red';
            const arrow = isPositive ? 'fa-arrow-up' : 'fa-arrow-down';

            // Safe Salary Display: Check if > 0
            const salaryDisplay = skill.salary > 0 ? `$${skill.salary}k` : '<span style="color:#ccc">N/A</span>';

            row.innerHTML = `
                <td class="skill-name">${skill.name}</td>
                <td><span class="category-tag ${catClass}">${catName}</span></td>
                <td>
                    <div class="demand-bar-sm">
                        <div class="demand-fill-sm" style="width: ${skill.demand}%"></div>
                    </div>
                    ${skill.demand}
                </td>
                <td style="color:${growthColor}"><i class="fas ${arrow}"></i> ${skill.growth}%</td>
                <td>${salaryDisplay}</td>
                <td>${skill.jobs.toLocaleString()}</td>
            `;
            tableBody.appendChild(row);
        });
    }

    // --- 6. FILTERS ---
    function setupFilters(allData) {
        const filterSection = document.querySelector('.filters-section');
        const newSection = filterSection.cloneNode(true);
        filterSection.parentNode.replaceChild(newSection, filterSection);

        newSection.addEventListener('click', (e) => {
            const btn = e.target.closest('.filter-btn');
            if (!btn) return;

            newSection.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const category = btn.getAttribute('data-filter');
            const filteredData = category === 'all'
                ? allData
                : allData.filter(s => s.category === category);

            renderChart(filteredData);
            renderTable(filteredData);

            // Optional: Update stats to reflect the filtered view?
            // If you want stats to ALWAYS show global totals, remove the line below.
            // If you want stats to update when you click "Backend", keep it.
            updateStatsCards(filteredData);
        });
    }
    // --- RECRUITER PROFILES LOGIC ---
    const btnFindInternships = document.getElementById('find-internships-btn');
const profileList = document.getElementById('profileList');

if (profileList) {

    // Wait for click if on the page with the button
    if (btnFindInternships) {
        btnFindInternships.addEventListener('click', () => {
            btnFindInternships.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Loading...';
            btnFindInternships.disabled = true;

            // Trigger the search ONLY when the user clicks
            loadMockInternships();
        });
    }
}

function loadMockInternships() {
    const mockData = [
        {
            role: "Supply Chain & Logistics Operations",
            company: "Oneworld Logistics Private Limited (Abhilaya)",
            activelyHiring: true,
            logo: "https://logo.clearbit.com/oneworldlogistics.in",
            location: "Mumbai",
            stipend: "₹ 12,000 - 15,000 /month",
            duration: "3 Months",
            desc: "Coordinate shipments and vendors, process orders, and maintain accurate logistics documentation",
            skills: ["MS-Excel", "Effective Communication"],
            posted: "3 weeks ago",
            ppoOffer: null
        },
        {
            role: "Digital Ad Sales & Business Development",
            company: "Ventes Avenues",
            activelyHiring: true,
            logo: "https://logo.clearbit.com/ventesavenues.com",
            location: "Gurgaon, Mumbai, Bangalore",
            stipend: "₹ 14,999 - 15,000 /month",
            duration: "6 Months",
            desc: "Generate leads, pitch digital marketing solutions, and handle client outreach via calls, emails, and...",
            skills: ["Presentation skills", "Client Interaction", "Digital Advertising", "Sales Management", "Business Development", "Interpersonal skills", "Effective Communication"],
            posted: "1 week ago",
            ppoOffer: "Job offer starting ₹ 3LPA post internship"
        }
    ];

    profileList.innerHTML = '';

    mockData.forEach(intern => {
        const card = document.createElement('div');
        card.className = 'recruiter-profile-card';

        const ppoHtml = intern.ppoOffer ? `<span class="rp-ppo"><i class="fas fa-briefcase"></i> ${intern.ppoOffer}</span>` : '';
        const hiringBadge = intern.activelyHiring ? `<span class="rp-badge-hiring">Actively hiring</span>` : '';

        card.innerHTML = `
                <div class="rp-header">
                    <div class="rp-title-section">
                        <h3 class="rp-role">${intern.role}</h3>
                        <div class="rp-company-info">
                            <span class="rp-company-name">${intern.company}</span>
                            ${hiringBadge}
                        </div>
                    </div>
                    <img src="${intern.logo}" alt="Logo" class="rp-logo" onerror="this.style.display='none'">
                </div>

                <div class="rp-details-row">
                    <div class="rp-detail-item"><i class="fas fa-location-dot"></i> ${intern.location}</div>
                    <div class="rp-detail-item"><i class="fas fa-money-bill-wave"></i> ${intern.stipend}</div>
                    <div class="rp-detail-item"><i class="far fa-calendar-alt"></i> ${intern.duration}</div>
                </div>

                <div class="rp-desc">
                    <i class="far fa-file-alt"></i> ${intern.desc}
                </div>

                <div class="rp-skills">
                    ${intern.skills.join('<span class="rp-dot">•</span>')}
                </div>

                <div class="rp-footer">
                    <span class="rp-posted"><i class="fas fa-history"></i> ${intern.posted}</span>
                    ${ppoHtml}
                </div>
            `;
        profileList.appendChild(card);
    });

    // Small fade in effect for smooth UI loading
    profileList.style.opacity = 0;
    setTimeout(() => {
        profileList.style.transition = 'opacity 0.4s ease';
        profileList.style.opacity = 1;
    }, 50);
}

// Initialize Dashboard only if elements exist on the current page
if (chartContainer && tableBody) {
    initDashboard();
}
});