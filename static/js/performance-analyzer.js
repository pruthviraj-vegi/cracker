/**
 * === Web Performance Analyzer ===
 * Author: Pruthvi x Cursor AI
 * 
 * Features:
 * - Measures DNS, TCP, TTFB, Response, DOM, and full page load times
 * - Core Web Vitals: FCP, LCP, CLS, INP (replacing FID)
 * - Advanced metrics: TTI, TBT, JavaScript execution time
 * - Resource sizes (transfer, decoded, encoded)
 * - Render-blocking resource identification
 * - Memory usage tracking
 * - Network waterfall visualization
 * - Lists individual resource timings
 * - Highlights slow assets (>300ms)
 * - Auto-prompts AI assistant to suggest optimization or missing data collection
 * - Real-time performance dashboard
 * - Export performance data
 */

class PerformanceAnalyzer {
    constructor() {
        this.metrics = {};
        this.resources = [];
        this.slowAssets = [];
        this.renderBlockingResources = [];
        this.networkWaterfall = [];
        this.isVisible = false;
        this.longTasks = [];
        this.interactions = [];
        this.init();
    }

    init() {
        // Analyze on load
        if (document.readyState === 'complete') {
            this.analyze().catch(console.error);
        } else {
            window.addEventListener('load', () => this.analyze().catch(console.error));
        }

        // Add keyboard shortcut (Ctrl+Shift+P)
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.shiftKey && e.key === 'P') {
                e.preventDefault();
                this.toggleDashboard();
            }
        });
    }

    async analyze() {
        const navEntries = performance.getEntriesByType("navigation")[0];
        const resources = performance.getEntriesByType("resource");

        console.log("=== Page Performance Metrics ===");

        // Get Core Web Vitals asynchronously
        const [lcp, inp] = await Promise.all([
            this.getLCP(),
            this.getINP()
        ]);

        // Calculate TTI and TBT
        const fcp = this.getFCP();
        const [tti, tbt] = await Promise.all([
            this.getTTI(fcp),
            this.getTBT(fcp)
        ]);

        // Get JavaScript execution time
        const jsExecutionTime = this.getJSExecutionTime(resources);

        // Get memory usage
        const memoryUsage = this.getMemoryUsage();

        this.metrics = {
            dnsLookup: navEntries.domainLookupEnd - navEntries.domainLookupStart,
            tcpConnection: navEntries.connectEnd - navEntries.connectStart,
            ttfb: navEntries.responseStart - navEntries.requestStart,
            responseTime: navEntries.responseEnd - navEntries.responseStart,
            domLoad: navEntries.domContentLoadedEventEnd - navEntries.startTime,
            fullPageLoad: navEntries.loadEventEnd - navEntries.startTime,
            // Core Web Vitals
            fcp: fcp,
            lcp: lcp,
            cls: this.getCLS(),
            inp: inp,
            // Additional metrics
            tti: tti,
            tbt: tbt,
            jsExecutionTime: jsExecutionTime,
            memoryUsage: memoryUsage
        };

        // Log metrics to console
        for (const [key, value] of Object.entries(this.metrics)) {
            if (key === 'memoryUsage') {
                if (value) {
                    console.log(`${key.replace(/([A-Z])/g, " $1")}:`,
                        `Used: ${this.formatBytes(value.usedJSHeapSize)}, ` +
                        `Total: ${this.formatBytes(value.totalJSHeapSize)}, ` +
                        `Limit: ${this.formatBytes(value.jsHeapSizeLimit)}`);
                } else {
                    console.log(`${key.replace(/([A-Z])/g, " $1")}:`, "Not available");
                }
            } else {
                const displayValue = typeof value === 'number'
                    ? `${value.toFixed(2)}${key === 'cls' ? '' : ' ms'}`
                    : value;
                console.log(`${key.replace(/([A-Z])/g, " $1")}:`, displayValue);
            }
        }

        console.log("\n=== Resource Load Times ===");

        // Enhanced resource tracking with sizes and render-blocking detection
        this.resources = resources.map(r => {
            const isRenderBlocking = this.isRenderBlocking(r);
            const resource = {
                type: r.initiatorType.toUpperCase(),
                name: r.name,
                duration: r.duration,
                transferSize: r.transferSize || 0,
                decodedSize: r.decodedBodySize || 0,
                encodedSize: r.encodedBodySize || 0,
                renderBlocking: isRenderBlocking,
                // Network waterfall phases
                waterfall: {
                    dns: r.domainLookupEnd - r.domainLookupStart,
                    tcp: r.connectEnd - r.connectStart,
                    ssl: r.secureConnectionStart > 0 ? r.connectEnd - r.secureConnectionStart : 0,
                    request: r.requestStart - (r.connectEnd || r.fetchStart),
                    response: r.responseEnd - r.responseStart,
                    processing: r.duration - (r.responseEnd - r.startTime)
                }
            };

            if (isRenderBlocking) {
                this.renderBlockingResources.push(resource);
            }

            return resource;
        });

        // Build network waterfall data
        this.networkWaterfall = this.buildWaterfallData(resources);

        this.resources.forEach((r) => {
            const duration = r.duration.toFixed(2);
            const size = this.formatBytes(r.transferSize);
            const blocking = r.renderBlocking ? ' [BLOCKING]' : '';
            console.log(`${r.type} → ${r.name} : ${duration} ms (${size})${blocking}`);

            // Track slow assets
            if (r.duration > 300) {
                this.slowAssets.push(r);
            }
        });

        // Detect potential issues
        this.detectIssues();

        // Generate AI prompt
        this.generateAIPrompt();

        // Calculate performance score
        this.calculatePerformanceScore();

        // Update dashboard if visible
        if (this.isVisible) {
            this.updateDashboard();
        }
    }

    detectIssues() {
        const missing = [];
        const warnings = [];

        // Critical issues
        if (this.metrics.fullPageLoad === 0) missing.push("Full page load time not captured");
        if (this.resources.length === 0) missing.push("No resource entries found (possible cache or CSP)");

        // Performance warnings
        if (this.metrics.ttfb > 200) warnings.push(`High TTFB (${this.metrics.ttfb.toFixed(2)}ms) - server response slow`);
        if (this.metrics.domLoad > 1000) warnings.push(`Slow DOM load (${this.metrics.domLoad.toFixed(2)}ms) - consider code splitting`);
        if (this.metrics.fcp > 1800) warnings.push(`Slow FCP (${this.metrics.fcp.toFixed(2)}ms) - first content paint delayed`);
        if (this.metrics.lcp > 2500) warnings.push(`Slow LCP (${this.metrics.lcp.toFixed(2)}ms) - largest content paint delayed`);
        if (this.metrics.cls > 0.1) warnings.push(`High CLS (${this.metrics.cls.toFixed(3)}) - layout shift detected`);
        if (this.metrics.inp > 200) warnings.push(`High INP (${this.metrics.inp.toFixed(2)}ms) - interaction delay detected`);
        if (this.metrics.tti > 5000) warnings.push(`Slow TTI (${this.metrics.tti.toFixed(2)}ms) - page takes long to become interactive`);
        if (this.metrics.tbt > 300) warnings.push(`High TBT (${this.metrics.tbt.toFixed(2)}ms) - main thread blocking detected`);
        if (this.metrics.jsExecutionTime > 1000) warnings.push(`High JS execution time (${this.metrics.jsExecutionTime.toFixed(2)}ms) - consider code splitting`);
        if (this.renderBlockingResources.length > 3) warnings.push(`${this.renderBlockingResources.length} render-blocking resources detected`);
        if (this.slowAssets.length > 5) warnings.push("Multiple slow assets detected - optimization needed");

        // Memory warnings
        if (this.metrics.memoryUsage) {
            const memoryMB = this.metrics.memoryUsage.usedJSHeapSize / (1024 * 1024);
            if (memoryMB > 50) warnings.push(`High memory usage (${memoryMB.toFixed(2)}MB) - potential memory leak`);
        }

        // Check for specific bottlenecks
        const fontLoad = this.resources.find(r => r.name.includes('fonts.googleapis.com'));
        if (fontLoad && fontLoad.duration > 150) warnings.push(`Slow font loading (${fontLoad.duration.toFixed(2)}ms) - consider font optimization`);

        const chartLoad = this.resources.find(r => r.name.includes('chart'));
        if (chartLoad && chartLoad.duration > 200) warnings.push(`Heavy chart library (${chartLoad.duration.toFixed(2)}ms) - consider lazy loading`);

        if (missing.length > 0) {
            console.warn("\n⚠️ Critical Issues Detected:");
            missing.forEach((m) => console.warn(" -", m));
        }

        if (warnings.length > 0) {
            console.warn("\n⚠️ Performance Warnings:");
            warnings.forEach((w) => console.warn(" -", w));
        }

        return [...missing, ...warnings];
    }

    calculatePerformanceScore() {
        // Calculate overall performance score (0-100)
        let score = 100;

        // Deduct points for slow metrics
        if (this.metrics.lcp > 2500) score -= 30;
        else if (this.metrics.lcp > 2000) score -= 20;
        else if (this.metrics.lcp > 1500) score -= 10;

        if (this.metrics.fcp > 1800) score -= 25;
        else if (this.metrics.fcp > 1200) score -= 15;
        else if (this.metrics.fcp > 800) score -= 5;

        if (this.metrics.cls > 0.25) score -= 20;
        else if (this.metrics.cls > 0.1) score -= 10;

        if (this.metrics.inp > 200) score -= 20;
        else if (this.metrics.inp > 100) score -= 10;

        if (this.metrics.tti > 5000) score -= 15;
        else if (this.metrics.tti > 3500) score -= 10;
        else if (this.metrics.tti > 2500) score -= 5;

        if (this.metrics.tbt > 300) score -= 15;
        else if (this.metrics.tbt > 200) score -= 10;
        else if (this.metrics.tbt > 100) score -= 5;

        if (this.metrics.jsExecutionTime > 2000) score -= 10;
        else if (this.metrics.jsExecutionTime > 1000) score -= 5;

        if (this.metrics.ttfb > 600) score -= 10;
        else if (this.metrics.ttfb > 200) score -= 5;

        // Deduct points for slow assets
        const slowAssetsCount = this.slowAssets.length;
        if (slowAssetsCount > 5) score -= 15;
        else if (slowAssetsCount > 3) score -= 10;
        else if (slowAssetsCount > 1) score -= 5;

        // Deduct points for render-blocking resources
        const blockingCount = this.renderBlockingResources.length;
        if (blockingCount > 5) score -= 10;
        else if (blockingCount > 3) score -= 5;

        this.performanceScore = Math.max(0, Math.min(100, score));

        // Log performance grade
        let grade = 'F';
        if (this.performanceScore >= 90) grade = 'A+';
        else if (this.performanceScore >= 80) grade = 'A';
        else if (this.performanceScore >= 70) grade = 'B';
        else if (this.performanceScore >= 60) grade = 'C';
        else if (this.performanceScore >= 50) grade = 'D';

        console.log(`\n🎯 Performance Score: ${this.performanceScore}/100 (Grade: ${grade})`);

        return this.performanceScore;
    }

    generateAIPrompt() {
        const memoryInfo = this.metrics.memoryUsage
            ? `Memory Usage: ${this.formatBytes(this.metrics.memoryUsage.usedJSHeapSize)} / ${this.formatBytes(this.metrics.memoryUsage.totalJSHeapSize)}`
            : 'Memory Usage: Not available';

        const aiPrompt = `
The following page performance metrics were collected:

Core Metrics:
${Object.entries(this.metrics)
                .filter(([k]) => k !== 'memoryUsage')
                .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v.toFixed(2)} ${k === 'cls' ? '' : 'ms'}`)
                .join("\n")}
${memoryInfo}

Resource Details (with sizes):
${this.resources
                .map((r) => `${r.type} → ${r.name} : ${r.duration.toFixed(2)}ms, Size: ${this.formatBytes(r.transferSize)}${r.renderBlocking ? ' [RENDER-BLOCKING]' : ''}`)
                .join("\n")}

Slow assets (>300ms):
${this.slowAssets.length > 0
                ? this.slowAssets.map((r) => `${r.type} → ${r.name} : ${r.duration.toFixed(2)}ms, Size: ${this.formatBytes(r.transferSize)}`).join("\n")
                : 'None'}

Render-blocking resources:
${this.renderBlockingResources.length > 0
                ? this.renderBlockingResources.map((r) => `${r.type} → ${r.name}`).join("\n")
                : 'None'}

JavaScript Execution Time: ${this.metrics.jsExecutionTime.toFixed(2)}ms
Total Blocking Time: ${this.metrics.tbt.toFixed(2)}ms
Time to Interactive: ${this.metrics.tti.toFixed(2)}ms

Network Waterfall (first 10 resources):
${this.networkWaterfall.slice(0, 10).map(r => {
                    const phases = Object.entries(r.phases)
                        .filter(([_, v]) => v !== null)
                        .map(([phase, data]) => `${phase}: ${data.duration.toFixed(2)}ms`)
                        .join(', ');
                    return `${r.name}: ${phases}`;
                }).join("\n")}

Now analyze this data and suggest:
1. Which assets should be optimized (slow >300ms, large sizes, render-blocking)
2. JavaScript execution time optimization opportunities
3. Render-blocking resource elimination strategies
4. Network waterfall optimization (parallel loading, resource hints)
5. Memory usage optimization if applicable
6. TTI and TBT improvements
7. Specific recommendations for this Django billing application
`;

        console.log("\n\n=== 💡 AI Optimization Prompt ===\n", aiPrompt);
        console.log("\nCopy the above prompt and give it to Cursor AI to suggest optimization.\n");

        return aiPrompt;
    }

    // Core Web Vitals measurement methods
    getFCP() {
        try {
            const fcpEntry = performance.getEntriesByName('first-contentful-paint')[0];
            return fcpEntry ? fcpEntry.startTime : 0;
        } catch (e) {
            return 0;
        }
    }

    getLCP() {
        return new Promise((resolve) => {
            try {
                if (!('PerformanceObserver' in window)) {
                    resolve(0);
                    return;
                }

                const observer = new PerformanceObserver((list) => {
                    const entries = list.getEntries();
                    const lastEntry = entries[entries.length - 1];
                    observer.disconnect();
                    resolve(lastEntry ? lastEntry.startTime : 0);
                });
                observer.observe({ entryTypes: ['largest-contentful-paint'] });

                // Timeout after 5 seconds
                setTimeout(() => resolve(0), 5000);
            } catch (e) {
                resolve(0);
            }
        });
    }

    getCLS() {
        try {
            if (!('PerformanceObserver' in window)) {
                return 0;
            }

            let clsValue = 0;
            const observer = new PerformanceObserver((list) => {
                for (const entry of list.getEntries()) {
                    if (!entry.hadRecentInput) {
                        clsValue += entry.value;
                    }
                }
            });
            observer.observe({ entryTypes: ['layout-shift'] });
            return clsValue;
        } catch (e) {
            return 0;
        }
    }

    getINP() {
        return new Promise((resolve) => {
            try {
                if (!('PerformanceObserver' in window)) {
                    resolve(0);
                    return;
                }

                const interactions = [];

                // Observe first-input (fallback)
                const firstInputObserver = new PerformanceObserver((list) => {
                    for (const entry of list.getEntries()) {
                        const latency = entry.processingStart ?
                            (entry.processingStart - entry.startTime) : 0;
                        interactions.push({
                            type: 'first-input',
                            latency: latency,
                            duration: entry.duration || 0,
                            startTime: entry.startTime
                        });
                    }
                });

                // Try to observe event entries (for INP)
                let eventObserver = null;
                try {
                    eventObserver = new PerformanceObserver((list) => {
                        for (const entry of list.getEntries()) {
                            // Only track user interactions (clicks, keypresses, taps)
                            if (['click', 'keydown', 'pointerdown'].includes(entry.name)) {
                                const latency = entry.processingStart ?
                                    (entry.processingStart - entry.startTime) :
                                    (entry.duration || 0);
                                interactions.push({
                                    type: entry.name,
                                    latency: latency,
                                    duration: entry.duration || 0,
                                    startTime: entry.startTime
                                });
                            }
                        }
                    });
                    eventObserver.observe({ entryTypes: ['event'] });
                } catch (e) {
                    // Event timing API not supported, use first-input only
                }

                firstInputObserver.observe({ entryTypes: ['first-input'] });

                // Calculate INP after 5 seconds
                setTimeout(() => {
                    firstInputObserver.disconnect();
                    if (eventObserver) { try { eventObserver.disconnect(); } catch (e) { /* ignore */ } }
                    this.interactions = interactions;
                    if (interactions.length === 0) {
                        resolve(0);
                        return;
                    }
                    const sorted = interactions.map(i => i.latency).sort((a, b) => b - a);
                    const inp = sorted.length > 0 ? sorted[0] : 0;
                    resolve(inp);
                }, 5000);
            } catch (e) {
                resolve(0);
            }
        });
    }

    getTTI(fcp) {
        return new Promise((resolve) => {
            try {
                if (!fcp || fcp === 0) {
                    resolve(0);
                    return;
                }

                // TTI is when main thread is quiet for 5 seconds after FCP
                // Simplified: use DOMContentLoaded + 5s quiet period check
                const domReady = performance.timing.domContentLoadedEventEnd - performance.timing.navigationStart;

                // Check for long tasks after FCP
                if ('PerformanceObserver' in window) {
                    const longTasks = [];
                    const observer = new PerformanceObserver((list) => {
                        for (const entry of list.getEntries()) {
                            if (entry.startTime >= fcp && entry.duration > 50) {
                                longTasks.push(entry);
                            }
                        }
                    });
                    observer.observe({ entryTypes: ['longtask'] });

                    setTimeout(() => {
                        observer.disconnect();
                        this.longTasks = longTasks;
                        if (longTasks.length > 0) {
                            const lastTask = longTasks[longTasks.length - 1];
                            resolve(lastTask.startTime + lastTask.duration + 5000);
                        } else {
                            resolve(domReady + 5000);
                        }
                    }, 10000);
                } else {
                    resolve(domReady + 5000);
                }
            } catch (e) {
                resolve(0);
            }
        });
    }

    getTBT(fcp) {
        return new Promise((resolve) => {
            try {
                if (!fcp || fcp === 0) {
                    resolve(0);
                    return;
                }

                // TBT is sum of blocking time (tasks > 50ms) between FCP and TTI
                if ('PerformanceObserver' in window) {
                    const blockingTime = [];
                    const observer = new PerformanceObserver((list) => {
                        for (const entry of list.getEntries()) {
                            if (entry.startTime >= fcp && entry.duration > 50) {
                                // Blocking time is duration - 50ms
                                blockingTime.push(entry.duration - 50);
                            }
                        }
                    });
                    observer.observe({ entryTypes: ['longtask'] });

                    setTimeout(() => {
                        observer.disconnect();
                        const tbt = blockingTime.reduce((sum, time) => sum + time, 0);
                        resolve(tbt);
                    }, 10000);
                } else {
                    resolve(0);
                }
            } catch (e) {
                resolve(0);
            }
        });
    }

    getJSExecutionTime(resources) {
        try {
            let totalJSTime = 0;
            const jsResources = resources.filter(r =>
                r.initiatorType === 'script' || r.name.endsWith('.js')
            );

            jsResources.forEach(r => {
                // Execution time is roughly the processing time
                const processingTime = r.duration - (r.responseEnd - r.startTime);
                if (processingTime > 0) {
                    totalJSTime += processingTime;
                }
            });

            // Also check for long tasks
            if (this.longTasks.length > 0) {
                this.longTasks.forEach(task => {
                    totalJSTime += task.duration;
                });
            }

            return totalJSTime;
        } catch (e) {
            return 0;
        }
    }

    getMemoryUsage() {
        try {
            if (performance.memory) {
                return {
                    usedJSHeapSize: performance.memory.usedJSHeapSize,
                    totalJSHeapSize: performance.memory.totalJSHeapSize,
                    jsHeapSizeLimit: performance.memory.jsHeapSizeLimit
                };
            }
            return null;
        } catch (e) {
            return null;
        }
    }

    isRenderBlocking(resource) {
        const name = resource.name.toLowerCase();
        const type = resource.initiatorType;

        if (type === 'link' || name.includes('.css')) {
            return true;
        }

        if (type === 'script' || name.includes('.js')) {
            // Check if the corresponding script tag has async/defer
            if (type === 'script') {
                const scripts = document.querySelectorAll('script[src]');
                for (const script of scripts) {
                    if (script.src === resource.name && (script.async || script.defer)) {
                        return false;
                    }
                }
            }
            return true;
        }

        // Fonts can block rendering
        if (name.includes('font') || name.includes('typeface')) {
            return true;
        }

        return false;
    }

    buildWaterfallData(resources) {
        return resources.map(r => ({
            name: r.name,
            startTime: r.startTime,
            duration: r.duration,
            phases: {
                dns: {
                    start: r.domainLookupStart,
                    end: r.domainLookupEnd,
                    duration: r.domainLookupEnd - r.domainLookupStart
                },
                tcp: {
                    start: r.connectStart,
                    end: r.connectEnd,
                    duration: r.connectEnd - r.connectStart
                },
                ssl: r.secureConnectionStart > 0 ? {
                    start: r.secureConnectionStart,
                    end: r.connectEnd,
                    duration: r.connectEnd - r.secureConnectionStart
                } : null,
                request: {
                    start: r.requestStart,
                    end: r.responseStart,
                    duration: r.responseStart - r.requestStart
                },
                response: {
                    start: r.responseStart,
                    end: r.responseEnd,
                    duration: r.responseEnd - r.responseStart
                },
                processing: {
                    start: r.responseEnd,
                    end: r.startTime + r.duration,
                    duration: r.duration - (r.responseEnd - r.startTime)
                }
            }
        })).sort((a, b) => a.startTime - b.startTime);
    }

    formatBytes(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    createDashboard() {
        const dashboard = document.createElement('div');
        dashboard.id = 'performance-dashboard';
        dashboard.className = 'perf-dashboard';
        dashboard.innerHTML = `
            <div class="perf-header">
                <h3>🚀 Performance Analyzer</h3>
                <div class="perf-controls">
                    <button class="perf-btn" id="perf-refresh">🔄</button>
                    <button class="perf-btn" id="perf-export">📊</button>
                    <button class="perf-btn" id="perf-close">✕</button>
                </div>
            </div>
            <div class="perf-content">
                <div class="perf-section">
                    <h4>📈 Core Metrics</h4>
                    <div class="perf-metrics" id="perf-metrics"></div>
                </div>
                <div class="perf-section">
                    <h4>📦 Resources</h4>
                    <div class="perf-resources" id="perf-resources"></div>
                </div>
                <div class="perf-section">
                    <h4>⚠️ Slow Assets</h4>
                    <div class="perf-slow" id="perf-slow"></div>
                </div>
                <div class="perf-section">
                    <h4>🚫 Render-Blocking</h4>
                    <div class="perf-blocking" id="perf-blocking"></div>
                </div>
                <div class="perf-section">
                    <h4>💾 Memory</h4>
                    <div class="perf-memory" id="perf-memory"></div>
                </div>
                <div class="perf-section">
                    <h4>🌊 Network Waterfall</h4>
                    <div class="perf-waterfall" id="perf-waterfall"></div>
                </div>
                <div class="perf-section">
                    <h4>🤖 AI Prompt</h4>
                    <textarea class="perf-prompt" id="perf-prompt" readonly></textarea>
                    <button class="perf-btn perf-copy" id="perf-copy">📋 Copy</button>
                </div>
            </div>
        `;

        document.body.appendChild(dashboard);

        // Add event listeners
        document.getElementById('perf-refresh').addEventListener('click', () => this.refresh().catch(console.error));
        document.getElementById('perf-export').addEventListener('click', () => this.exportData());
        document.getElementById('perf-close').addEventListener('click', () => this.toggleDashboard());
        document.getElementById('perf-copy').addEventListener('click', () => this.copyPrompt());
    }

    updateDashboard() {
        // Build all content strings first, then apply in a single rAF to reduce reflows
        const metricsHtml = Object.entries(this.metrics)
            .filter(([key]) => key !== 'memoryUsage')
            .map(([key, value]) => {
                const displayValue = typeof value === 'number'
                    ? `${value.toFixed(2)} ${key === 'cls' ? '' : 'ms'}`
                    : String(value);
                return `
                    <div class="perf-metric">
                        <span class="perf-label">${key.replace(/([A-Z])/g, " $1")}</span>
                        <span class="perf-value ${this.getMetricClass(key, value)}">${displayValue}</span>
                    </div>
                `;
            }).join('');

        const resourcesHtml = this.resources
            .slice(0, 10)
            .map(r => `
                <div class="perf-resource ${r.duration > 300 ? 'slow' : ''} ${r.renderBlocking ? 'blocking' : ''}">
                    <span class="perf-resource-type">${r.type}</span>
                    <span class="perf-resource-name">${this.truncateUrl(r.name)}</span>
                    <span class="perf-resource-duration">${r.duration.toFixed(2)} ms</span>
                    <span class="perf-resource-size">${this.formatBytes(r.transferSize)}</span>
                    ${r.renderBlocking ? '<span class="perf-badge">BLOCKING</span>' : ''}
                </div>
            `).join('');

        const slowHtml = this.slowAssets.length > 0
            ? this.slowAssets.map(r => `
                <div class="perf-slow-asset">
                    <span class="perf-resource-type">${r.type}</span>
                    <span class="perf-resource-name">${this.truncateUrl(r.name)}</span>
                    <span class="perf-resource-duration slow">${r.duration.toFixed(2)} ms</span>
                    <span class="perf-resource-size">${this.formatBytes(r.transferSize)}</span>
                </div>
            `).join('')
            : '<div class="perf-no-slow">✅ No slow assets detected</div>';

        const blockingHtml = this.renderBlockingResources.length > 0
            ? this.renderBlockingResources.map(r => `
                <div class="perf-blocking-resource">
                    <span class="perf-resource-type">${r.type}</span>
                    <span class="perf-resource-name">${this.truncateUrl(r.name)}</span>
                    <span class="perf-resource-duration">${r.duration.toFixed(2)} ms</span>
                </div>
            `).join('')
            : '<div class="perf-no-slow">✅ No render-blocking resources</div>';

        const memoryHtml = this.metrics.memoryUsage
            ? (() => {
                const used = this.formatBytes(this.metrics.memoryUsage.usedJSHeapSize);
                const total = this.formatBytes(this.metrics.memoryUsage.totalJSHeapSize);
                const limit = this.formatBytes(this.metrics.memoryUsage.jsHeapSizeLimit);
                const percent = ((this.metrics.memoryUsage.usedJSHeapSize / this.metrics.memoryUsage.totalJSHeapSize) * 100).toFixed(1);
                return `<div class="perf-memory-info"><div>Used: ${used} (${percent}%)</div><div>Total: ${total}</div><div>Limit: ${limit}</div></div>`;
            })()
            : '<div class="perf-no-slow">Memory API not available</div>';

        const waterfallHtml = this.networkWaterfall.length > 0
            ? this.networkWaterfall.slice(0, 5).map(r => {
                const phases = Object.entries(r.phases)
                    .filter(([_, v]) => v !== null)
                    .map(([phase, data]) => `${phase}: ${data.duration.toFixed(0)}ms`)
                    .join(' | ');
                return `<div class="perf-waterfall-item"><div class="perf-waterfall-name">${this.truncateUrl(r.name)}</div><div class="perf-waterfall-phases">${phases}</div></div>`;
            }).join('')
            : '<div class="perf-no-slow">No waterfall data</div>';

        // Batch all DOM writes in one rAF
        requestAnimationFrame(() => {
            document.getElementById('perf-metrics').innerHTML = metricsHtml;
            document.getElementById('perf-resources').innerHTML = resourcesHtml;
            document.getElementById('perf-slow').innerHTML = slowHtml;
            document.getElementById('perf-blocking').innerHTML = blockingHtml;
            document.getElementById('perf-memory').innerHTML = memoryHtml;
            document.getElementById('perf-waterfall').innerHTML = waterfallHtml;
        });

        document.getElementById('perf-prompt').value = this.generateAIPrompt();
    }

    getMetricClass(key, value) {
        if (typeof value !== 'number') return 'good';

        const thresholds = {
            dnsLookup: 100,
            tcpConnection: 200,
            ttfb: 1000,
            responseTime: 500,
            domLoad: 3000,
            fullPageLoad: 5000,
            fcp: 1800,
            lcp: 2500,
            inp: 200,
            tti: 5000,
            tbt: 300,
            jsExecutionTime: 1000,
            cls: 0.1
        };

        const threshold = thresholds[key];
        if (!threshold) return 'good';

        if (value > threshold) return 'slow';
        if (value > threshold * 0.7) return 'warning';
        return 'good';
    }

    truncateUrl(url) {
        if (url.length > 50) {
            return url.substring(0, 47) + '...';
        }
        return url;
    }

    toggleDashboard() {
        // Lazy-create dashboard on first open
        if (!document.getElementById('performance-dashboard')) {
            this.createDashboard();
        }

        const dashboard = document.getElementById('performance-dashboard');
        this.isVisible = !this.isVisible;

        if (this.isVisible) {
            dashboard.classList.add('visible');
            this.updateDashboard();
        } else {
            dashboard.classList.remove('visible');
        }
    }

    async refresh() {
        await this.analyze();
        this.updateDashboard();
    }

    exportData() {
        const data = {
            timestamp: new Date().toISOString(),
            url: window.location.href,
            metrics: this.metrics,
            resources: this.resources,
            slowAssets: this.slowAssets,
            renderBlockingResources: this.renderBlockingResources,
            networkWaterfall: this.networkWaterfall,
            longTasks: this.longTasks,
            interactions: this.interactions,
            userAgent: navigator.userAgent
        };

        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `performance-${Date.now()}.json`;
        a.click();
        URL.revokeObjectURL(url);
    }

    copyPrompt() {
        const prompt = document.getElementById('perf-prompt');
        prompt.select();
        document.execCommand('copy');

        // Show feedback
        const btn = document.getElementById('perf-copy');
        const originalText = btn.textContent;
        btn.textContent = '✅ Copied!';
        setTimeout(() => {
            btn.textContent = originalText;
        }, 2000);
    }
}

// Initialize performance analyzer
const perfAnalyzer = new PerformanceAnalyzer();

// Expose global function for manual analysis
window.analyzePerformance = () => perfAnalyzer.analyze().catch(console.error);
window.togglePerformanceDashboard = () => perfAnalyzer.toggleDashboard();
