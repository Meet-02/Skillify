document.addEventListener('DOMContentLoaded', () => {
    const puzzleContainer = document.querySelector('.puzzle-container');
    const puzzleScene     = document.querySelector('.puzzle-scene');

    // Scroll Interaction: Snap pieces together
    window.addEventListener('scroll', () => {
        const scrollY = window.scrollY;
        if (scrollY > 50) {
            puzzleContainer.classList.add('puzzle-solved');
        } else {
            puzzleContainer.classList.remove('puzzle-solved');
        }
        if (puzzleScene) {
            puzzleScene.style.transform = `rotateX(${-15 + scrollY * 0.05}deg) rotateY(${25 + scrollY * 0.1}deg)`;
        }
    });

    // Mouse Interaction: Tilt Scene
    if (puzzleContainer && puzzleScene) {
        puzzleContainer.addEventListener('mousemove', (e) => {
            const rect  = puzzleContainer.getBoundingClientRect();
            const x     = (e.clientX - rect.left) / rect.width;
            const y     = (e.clientY - rect.top)  / rect.height;
            const mouseX = (x - 0.5) * 2;
            const mouseY = (y - 0.5) * 2;
            const tiltX  = -15 + (-mouseY * 10);
            const tiltY  = 25  + (mouseX  * 10);
            puzzleScene.style.transform = `rotateX(${tiltX}deg) rotateY(${tiltY}deg)`;
        });

        puzzleContainer.addEventListener('mouseleave', () => {
            const scrollY = window.scrollY;
            puzzleScene.style.transform = `rotateX(${-15 + scrollY * 0.05}deg) rotateY(${25 + scrollY * 0.1}deg)`;
        });
    }

    // Resume Upload Logic
    const fileInput      = document.getElementById('file-input');
    const fileNameEl     = document.getElementById('file-name');
    const selectedFileDiv = document.getElementById('selected-file');
    const uploadArea     = document.getElementById('upload-area');

    if (fileInput) {
        fileInput.addEventListener('change', function () {
            if (this.files && this.files[0]) {
                fileNameEl.textContent             = this.files[0].name;
                selectedFileDiv.style.display      = 'flex';
                uploadArea.style.borderColor       = '#4f46e5';
                uploadArea.style.backgroundColor   = '#f5f3ff';
            }
        });

        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.style.borderColor     = '#4f46e5';
            uploadArea.style.backgroundColor = '#f5f3ff';
        });

        uploadArea.addEventListener('dragleave', (e) => {
            e.preventDefault();
            uploadArea.style.borderColor     = '#e2e8f0';
            uploadArea.style.backgroundColor = 'transparent';
        });
    }
});

document.addEventListener('DOMContentLoaded', () => {

    const chartContainer      = document.getElementById('skillDemandChart');
    const growthListContainer = document.getElementById('fastestGrowingList');
    const tableBody           = document.getElementById('skillsTableBody');

    const totalSkillsEl = document.getElementById('total-skills-stat');
    const avgGrowthEl   = document.getElementById('avg-growth-stat');
    const avgSalaryEl   = document.getElementById('avg-salary-stat');
    const totalJobsEl   = document.getElementById('total-jobs-stat');

    async function initDashboard() {
        const chartContainer = document.getElementById('skillDemandChart');
        if (!chartContainer) return;

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

        const response  = await fetch('/api/market-data');
        const rawData   = await response.json();
        const skillsData = processData(rawData);
        localStorage.setItem('marketDataCache', JSON.stringify(skillsData));

        renderChart(skillsData);
        renderGrowthList(skillsData);
        renderTable(skillsData);
        updateStatsCards(skillsData);
        setupFilters(skillsData);
    }

    function processData(apiData) {
        const maxJobs = Math.max(...apiData.map(d => d.jobs)) || 1;
        return apiData.map(item => {
            const demandScore = Math.round((item.jobs / maxJobs) * 100);
            const salaryK     = Math.round(item.salary / 1000);
            const mockGrowth  = Math.floor(Math.random() * 30) - 5;
            return {
                name:     item.name,
                category: categorizeSkill(item.name),
                demand:   demandScore,
                growth:   mockGrowth,
                salary:   salaryK,
                jobs:     item.jobs,
                trend:    mockGrowth > 0 ? 'up' : 'down'
            };
        });
    }

    function updateStatsCards(data) {
        if (!data || data.length === 0) return;
        if (totalSkillsEl) totalSkillsEl.textContent = data.length;

        const totalGrowth = data.reduce((sum, item) => sum + item.growth, 0);
        const avgGrowth   = Math.round(totalGrowth / data.length);
        if (avgGrowthEl) {
            const sign = avgGrowth > 0 ? '+' : '';
            avgGrowthEl.textContent  = `${sign}${avgGrowth}%`;
            avgGrowthEl.style.color  = avgGrowth >= 0 ? 'var(--success, green)' : 'var(--danger, red)';
        }

        const validSalaries = data.filter(item => item.salary > 0);
        const totalSalary   = validSalaries.reduce((sum, item) => sum + item.salary, 0);
        const avgSalary     = validSalaries.length ? Math.round(totalSalary / validSalaries.length) : 0;
        if (avgSalaryEl) avgSalaryEl.textContent = avgSalary > 0 ? `$${avgSalary}k` : 'N/A';

        const totalJobs = data.reduce((sum, item) => sum + item.jobs, 0);
        if (totalJobsEl) {
            totalJobsEl.textContent = totalJobs > 1000
                ? `${(totalJobs / 1000).toFixed(1)}k`
                : totalJobs;
        }
    }

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
            const isPositive  = skill.growth >= 0;
            const colorStyle  = isPositive ? 'color:green;' : 'color:red;';
            const iconClass   = isPositive ? 'fa-arrow-up' : 'fa-arrow-down';
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
            tableBody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:20px;">No skills found.</td></tr>';
            return;
        }
        data.forEach(skill => {
            const row       = document.createElement('tr');
            const catClass  = `cat-${skill.category}`;
            const catName   = skill.category.charAt(0).toUpperCase() + skill.category.slice(1);
            const isPositive      = skill.trend === 'up';
            const growthColor     = isPositive ? 'green' : 'red';
            const arrow           = isPositive ? 'fa-arrow-up' : 'fa-arrow-down';
            const salaryDisplay   = skill.salary > 0 ? `$${skill.salary}k` : '<span style="color:#ccc">N/A</span>';
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

    function setupFilters(allData) {
        const filterSection = document.querySelector('.filters-section');
        const newSection    = filterSection.cloneNode(true);
        filterSection.parentNode.replaceChild(newSection, filterSection);
        newSection.addEventListener('click', (e) => {
            const btn = e.target.closest('.filter-btn');
            if (!btn) return;
            newSection.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const category     = btn.getAttribute('data-filter');
            const filteredData = category === 'all'
                ? allData
                : allData.filter(s => s.category === category);
            renderChart(filteredData);
            renderTable(filteredData);
            updateStatsCards(filteredData);
        });
    }

    // --- RECRUITER PROFILES LOGIC ---
    const btnFindInternships = document.getElementById('find-internships-btn');
    const profileList        = document.getElementById('profileList');

    if (profileList) {
        if (btnFindInternships) {
            btnFindInternships.addEventListener('click', () => {
                btnFindInternships.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Loading...';
                btnFindInternships.disabled  = true;
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
            const card     = document.createElement('div');
            card.className = 'recruiter-profile-card';
            const ppoHtml      = intern.ppoOffer
                ? `<span class="rp-ppo"><i class="fas fa-briefcase"></i> ${intern.ppoOffer}</span>` : '';
            const hiringBadge  = intern.activelyHiring
                ? `<span class="rp-badge-hiring">Actively hiring</span>` : '';
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

        profileList.style.opacity = '0';
        setTimeout(() => {
            profileList.style.transition = 'opacity 0.4s ease';
            profileList.style.opacity    = '1';
        }, 50);
    }

    if (chartContainer && tableBody) {
        initDashboard();
    }
});


/* ════════════════════════════════════════════════════════════════════════════
   LIME MATCH INTELLIGENCE WIDGET
   ════════════════════════════════════════════════════════════════════════════
   buildMatchIntelligence(job) → HTML string
   
   Renders four zones beneath a job card:
     Zone 1 — Resume Strengths       (green, positive LIME weights)
     Zone 2 — Score Dilutions        (rose,  negative LIME weights + swap tips)
     Zone 3 — Missing Core Keywords  (slate, missing_skills checklist)
     Zone 4 — AI Next Step Banner    (dynamic colour based on gap_severity)
   
   Called from buildCard(job) in internship.html's inline <script>.
   Designed to degrade gracefully: each zone only renders if its data exists.
   ════════════════════════════════════════════════════════════════════════════ */

/**
 * Picks a contextual swap suggestion for a negative-weight word.
 * Looks at missing_skills categories to find a relevant replacement.
 *
 * Strategy:
 *   1. Flatten all missing skill arrays.
 *   2. Check if any missing skill shares a category keyword with the
 *      negative word (e.g. both are databases, both are frameworks).
 *   3. Fall back to the first available missing skill, else generic message.
 *
 * @param {string}   word          - the out-of-scope word (e.g. "mysql")
 * @param {Object}   missingSkills - {technical:[...], tools:[...], soft:[...]}
 * @returns {string} suggestion sentence
 */
function _getSwapSuggestion(word, missingSkills) {
    // Flatten all missing skills from all categories
    const allMissing = Object.values(missingSkills || {}).flat().filter(Boolean);

    // ── Polished default when no missing skills exist ────────────────────────
    if (!allMissing.length) {
        return `Your resume highlights "${word}", but this specific term does not appear anywhere in the job description. To strengthen your alignment, review the posting carefully and replace or supplement "${word}" with the exact keywords and phrases the employer has used. Tailoring your language to mirror their requirements will sharpen your semantic match and help your application stand out.`;
    }

    // ── Expanded heuristic category buckets ──────────────────────────────────
    const dbTerms      = ['sql', 'mysql', 'postgresql', 'mongodb', 'redis', 'cassandra', 'sqlite', 'database', 'dynamodb', 'firebase', 'supabase', 'nosql', 'mariadb', 'oracle'];
    const frameTerms   = ['react', 'vue', 'angular', 'django', 'flask', 'fastapi', 'express', 'spring', 'laravel', 'rails', 'nextjs', 'nuxt', 'svelte', 'gatsby', 'remix', 'node.js'];
    const cloudTerms   = ['aws', 'azure', 'gcp', 'docker', 'kubernetes', 'terraform', 'heroku', 'vercel', 'netlify', 'lambda', 'cloudflare'];
    const langTerms    = ['python', 'javascript', 'typescript', 'java', 'go', 'rust', 'c++', 'c#', 'php', 'ruby', 'swift', 'kotlin', 'r', 'scala', 'perl'];
    const softTerms    = ['communication', 'leadership', 'teamwork', 'management', 'collaboration', 'presentation', 'problem-solving', 'critical thinking', 'adaptability'];
    const testTerms    = ['testing', 'jest', 'mocha', 'selenium', 'cypress', 'pytest', 'junit', 'qa', 'unit test', 'integration test', 'software testing'];
    const dataTerms    = ['pandas', 'numpy', 'scipy', 'matplotlib', 'tableau', 'power bi', 'data analysis', 'data structures', 'statistics', 'analytics', 'excel'];
    const designTerms  = ['figma', 'sketch', 'photoshop', 'illustrator', 'xd', 'ui', 'ux', 'wireframe', 'prototype', 'canva'];
    const devopsTerms  = ['ci/cd', 'jenkins', 'github actions', 'gitlab', 'ansible', 'puppet', 'chef', 'git', 'version control', 'rest api', 'api'];

    const buckets = [dbTerms, frameTerms, cloudTerms, langTerms, softTerms, testTerms, dataTerms, designTerms, devopsTerms];
    const w       = word.toLowerCase();

    // Find which bucket the negative word belongs to
    const wordBucket = buckets.find(b => b.some(t => w.includes(t) || t.includes(w)));

    if (wordBucket) {
        // Try to find a missing skill in the same bucket
        const sameCategoryMissing = allMissing.find(ms =>
            wordBucket.some(t => ms.toLowerCase().includes(t) || t.includes(ms.toLowerCase()))
        );
        if (sameCategoryMissing) {
            return `The employer does not mention "${word}" in this role. Instead, they are specifically looking for "${sameCategoryMissing}", which falls within the same skill category. Replacing or supplementing "${word}" with "${sameCategoryMissing}" on your resume will directly boost your semantic alignment and improve your overall match score for this position.`;
        }
    }

    // ── Contextual fallback: pick the most relevant missing skill ────────────
    // Try to find a missing skill that shares at least a partial token with the word
    const partialMatch = allMissing.find(ms => {
        const msLower = ms.toLowerCase();
        return msLower.split(/\s+/).some(tok => w.includes(tok) || tok.includes(w));
    });

    if (partialMatch) {
        return `Your resume features "${word}", but the employer is looking for "${partialMatch}" instead. These terms are related, so updating your resume to specifically reference "${partialMatch}" — rather than the broader "${word}" — will tighten your alignment with the job requirements and contribute to a higher match score.`;
    }

    // ── Generic fallback using the first missing skill ───────────────────────
    const suggestion = allMissing[0];
    const extraSkills = allMissing.length > 1
        ? ` Additionally, consider adding "${allMissing[1]}" to further strengthen your profile.`
        : '';
    return `Your resume includes "${word}", which the employer has not listed as a requirement for this position. They are actively seeking candidates with "${suggestion}" experience.${extraSkills} Incorporating these targeted keywords into your resume while de-emphasizing out-of-scope terms like "${word}" will help close the gap and meaningfully improve your overall match.`;
}


/**
 * Renders the full LIME Match Intelligence widget for one job card.
 *
 * @param {Object} job - the full job object from the API response
 * @returns {string}   - HTML string (empty string if no LIME data + no missing skills)
 */
function buildMatchIntelligence(job) {
    const impact       = job.semantic_keyword_impact || {};
    const missingSkills = job.missing_skills || {};
    const severity     = job.gap_severity || 'High';

    const impactEntries = Object.entries(impact);
    const allMissing    = Object.values(missingSkills).flat().filter(Boolean);

    // Don't render widget at all if there's nothing meaningful to show
    if (!impactEntries.length && !allMissing.length) return '';

    // ── Split LIME entries into positive and negative ───────────────────────
    const positives = impactEntries
        .filter(([, w]) => w > 0)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 6);

    const negatives = impactEntries
        .filter(([, w]) => w < 0)
        .sort((a, b) => a[1] - b[1])   // most negative first
        .slice(0, 5);

    // ── Zone 1: Resume Strengths ────────────────────────────────────────────
    let zone1Html = '';
    if (positives.length) {
        const chips = positives.map(([word, weight]) => {
            const pct = (Math.abs(weight) * 100).toFixed(1);
            return `<span class="ski-chip ski-strength" title="Boosts semantic match by ${pct}%">
                        <span class="ski-chip-icon">▲</span>${escHtml(word)}
                        <span class="ski-chip-pct">+${pct}%</span>
                    </span>`;
        }).join('');

        zone1Html = `
        <div class="ski-zone ski-zone--strength">
            <div class="ski-zone-header">
                <span class="ski-zone-icon">✅</span>
                <div>
                    <div class="ski-zone-title">Your Resume Strengths</div>
                    <div class="ski-zone-sub">These keywords align with the job description and are driving your score up.</div>
                </div>
            </div>
            <div class="ski-chips">${chips}</div>
        </div>`;
    }

    // ── Zone 2: Score Dilutions ─────────────────────────────────────────────
    let zone2Html = '';
    if (negatives.length) {
        const chips = negatives.map(([word, weight]) => {
            const pct        = (Math.abs(weight) * 100).toFixed(1);
            const suggestion = _getSwapSuggestion(word, missingSkills);
            // Use ||| as a safe delimiter that won't appear in natural text
            const impactStr  = `Impact: -${pct}% (Out of Scope)`;
            const recStr     = `Recommendation: ${suggestion}`;
            const safeTip    = `${impactStr}|||${recStr}`
                .replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            return `<span class="ski-chip ski-dilution ski-tooltip-trigger"
                         data-tip="${safeTip}"
                         title="Impact: -${pct}% — hover for swap tip">
                        <span class="ski-chip-icon">▼</span>${escHtml(word)}
                        <span class="ski-chip-pct">-${pct}%</span>
                    </span>`;
        }).join('');

        zone2Html = `
        <div class="ski-zone ski-zone--dilution">
            <div class="ski-zone-header">
                <span class="ski-zone-icon">⚠️</span>
                <div>
                    <div class="ski-zone-title">Score Dilution / Out of Scope</div>
                    <div class="ski-zone-sub">These words pull your semantic match down — the employer didn't mention them, diluting your core vector focus.</div>
                </div>
            </div>
            <div class="ski-chips">${chips}</div>
        </div>`;
    }

    // ── Zone 3: Missing Core Keywords checklist ─────────────────────────────
    let zone3Html = '';
    if (allMissing.length) {
        // Flatten with category labels for context
        const items = [];
        const catLabels = { technical: 'Technical', tools: 'Tool', soft: 'Soft Skill' };
        for (const [cat, skills] of Object.entries(missingSkills)) {
            (skills || []).forEach(skill => {
                if (skill) items.push({ skill, cat, label: catLabels[cat] || cat });
            });
        }

        const checkItems = items.map((item, idx) => {
            const uid = `ski-check-${Math.random().toString(36).slice(2, 8)}-${idx}`;
            return `
            <label class="ski-check-item" for="${uid}">
                <input type="checkbox" class="ski-check-input" id="${uid}">
                <span class="ski-check-box"><i class="fas fa-check ski-check-mark"></i></span>
                <span class="ski-check-label">${escHtml(item.skill)}</span>
                <span class="ski-check-cat ski-cat-${item.cat}">${item.label}</span>
            </label>`;
        }).join('');

        zone3Html = `
        <div class="ski-zone ski-zone--missing">
            <div class="ski-zone-header">
                <span class="ski-zone-icon">➕</span>
                <div>
                    <div class="ski-zone-title">Missing Core Keywords</div>
                    <div class="ski-zone-sub">Add these exact terms from the job description to instantly boost your score. Check them off as you update your resume.</div>
                </div>
            </div>
            <div class="ski-checklist">${checkItems}</div>
        </div>`;
    }

    // ── Zone 4: AI Next Step Banner ─────────────────────────────────────────
    const bannerConfig = {
        High:   {
            cls:  'ski-banner--high',
            icon: '⚠️',
            text: 'Your resume is missing core technical frameworks. Focus on incorporating the Missing Core Keywords listed above to move into the interview tracking tier.'
        },
        Medium: {
            cls:  'ski-banner--medium',
            icon: '⚡',
            text: 'You have a solid foundation! Swapping out 2–3 out-of-scope phrases for their exact requested tool alternatives will optimize your match.'
        },
        Low:    {
            cls:  'ski-banner--low',
            icon: '🎉',
            text: 'Excellent alignment! Your vector profile matches the core parameters perfectly. Proceed with confidence.'
        }
    };

    const banner = bannerConfig[severity] || bannerConfig.High;
    const nextStepLabels = { High: 'Next Step', Medium: 'Next Step', Low: 'Next Step' };
    const zone4Html = `
    <div class="ski-banner ${banner.cls}">
        <span class="ski-banner-icon">${banner.icon}</span>
        <div class="ski-banner-body">
            <span class="ski-banner-label">${nextStepLabels[severity] || 'Next Step'}:</span>
            ${banner.text}
        </div>
    </div>`;

    // ── Assemble widget ─────────────────────────────────────────────────────
    return `
    <div class="ski-widget">
        <div class="ski-widget-header">
            <i class="fas fa-brain ski-widget-icon"></i>
            <span>Match Intelligence</span>
        </div>
        <div class="ski-zones">
            ${zone1Html}
            ${zone2Html}
            ${zone3Html}
        </div>
        ${zone4Html}
    </div>`;
}


/* ════════════════════════════════════════════════════════════════════════════
   CONTEXTUAL SWAP TOOLTIP — rich hover panel for dilution chips
   
   Instead of the native title= tooltip (plain text, no HTML),
   we render a custom floating panel positioned above each ▼ chip.
   Uses event delegation on #jobGrid so it works after every renderJobs() call.
   ════════════════════════════════════════════════════════════════════════════ */
(function initSwapTooltips() {
    // One shared tooltip div, repositioned on demand
    let tip = document.getElementById('ski-global-tip');
    if (!tip) {
        tip = document.createElement('div');
        tip.id        = 'ski-global-tip';
        tip.className = 'ski-global-tip';
        document.body.appendChild(tip);
    }

    function showTip(trigger, html) {
        tip.innerHTML = html;
        tip.classList.add('ski-global-tip--visible');

        const rect   = trigger.getBoundingClientRect();
        const tipW   = tip.offsetWidth  || 280;
        const tipH   = tip.offsetHeight || 80;
        const scrollY = window.scrollY || document.documentElement.scrollTop;
        const scrollX = window.scrollX || document.documentElement.scrollLeft;

        // Default: above the chip, centred
        let top  = rect.top  + scrollY - tipH - 10;
        let left = rect.left + scrollX + (rect.width / 2) - (tipW / 2);

        // Clamp to viewport
        if (left < 8)                          left = 8;
        if (left + tipW > window.innerWidth - 8) left = window.innerWidth - tipW - 8;
        if (top < scrollY + 8)                 top  = rect.bottom + scrollY + 10; // flip below

        tip.style.top  = `${top}px`;
        tip.style.left = `${left}px`;
    }

    function hideTip() {
        tip.classList.remove('ski-global-tip--visible');
    }

    // Delegate from document so it works after DOM updates
    document.addEventListener('mouseover', (e) => {
        const trigger = e.target.closest('.ski-tooltip-trigger');
        if (!trigger) return;
        const rawTip = trigger.dataset.tip || '';
        if (!rawTip) return;
        // Split on the safe ||| delimiter between Impact and Recommendation
        let html;
        const parts = rawTip.split('|||');
        if (parts.length >= 2) {
            const impactPart = parts[0].trim();
            const recPart    = parts.slice(1).join('|||').trim(); // rejoin in case ||| appears elsewhere
            // Extract just the recommendation text after "Recommendation: " prefix
            const recText = recPart.startsWith('Recommendation: ')
                ? recPart.substring('Recommendation: '.length)
                : recPart;
            html = `<span class="ski-tip-impact">${impactPart}</span><br><span class="ski-tip-rec-label">Recommendation:</span> ${recText}`;
        } else {
            html = rawTip;
        }
        showTip(trigger, html);
    });

    document.addEventListener('mouseout', (e) => {
        if (e.target.closest('.ski-tooltip-trigger') && !e.relatedTarget?.closest('.ski-tooltip-trigger')) {
            hideTip();
        }
    });

    // Also hide on scroll to avoid stale positioning
    window.addEventListener('scroll', hideTip, { passive: true });
})();
