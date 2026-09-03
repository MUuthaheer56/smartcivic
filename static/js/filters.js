/**
 * SmartCivic — Reusable Filter Bar Controller
 * Inspired by 21st.dev notification & data-table filter components.
 */
class SmartCivicFilter {
    constructor(options = {}) {
        this.containerId = options.containerId || 'filterBar';
        this.onFilterChange = options.onFilterChange || function() {};
        
        this.state = {
            search: '',
            status: 'all',
            categories: new Set(),
        };

        this.init();
    }

    init() {
        const container = document.getElementById(this.containerId);
        if (!container) return;

        // Search input
        const searchInput = container.querySelector('#filterSearchInput');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this.state.search = e.target.value.trim().toLowerCase();
                this.notify();
            });
        }

        // Status chips
        const statusChips = container.querySelectorAll('.status-chip');
        statusChips.forEach(chip => {
            chip.addEventListener('click', () => {
                statusChips.forEach(c => c.classList.remove('active'));
                chip.classList.add('active');
                this.state.status = chip.getAttribute('data-status') || 'all';
                this.notify();
            });
        });

        // Category chips
        const categoryChips = container.querySelectorAll('.category-chip');
        categoryChips.forEach(chip => {
            chip.addEventListener('click', () => {
                const cat = chip.getAttribute('data-category');
                if (!cat) return;

                if (cat === 'all') {
                    this.state.categories.clear();
                    categoryChips.forEach(c => c.classList.remove('active'));
                    chip.classList.add('active');
                } else {
                    const allChip = container.querySelector('.category-chip[data-category="all"]');
                    if (allChip) allChip.classList.remove('active');

                    if (this.state.categories.has(cat)) {
                        this.state.categories.delete(cat);
                        chip.classList.remove('active');
                    } else {
                        this.state.categories.add(cat);
                        chip.classList.add('active');
                    }

                    if (this.state.categories.size === 0 && allChip) {
                        allChip.classList.add('active');
                    }
                }
                this.notify();
            });
        });

        // Clear filters button
        const clearBtn = container.querySelector('#filterClearBtn');
        if (clearBtn) {
            clearBtn.addEventListener('click', () => this.reset());
        }
    }

    reset() {
        const container = document.getElementById(this.containerId);
        if (!container) return;

        this.state.search = '';
        this.state.status = 'all';
        this.state.categories.clear();

        const searchInput = container.querySelector('#filterSearchInput');
        if (searchInput) searchInput.value = '';

        const statusChips = container.querySelectorAll('.status-chip');
        statusChips.forEach(c => c.classList.remove('active'));
        const allStatusChip = container.querySelector('.status-chip[data-status="all"]');
        if (allStatusChip) allStatusChip.classList.add('active');

        const categoryChips = container.querySelectorAll('.category-chip');
        categoryChips.forEach(c => c.classList.remove('active'));
        const allCatChip = container.querySelector('.category-chip[data-category="all"]');
        if (allCatChip) allCatChip.classList.add('active');

        this.notify();
    }

    updateBadge(filteredCount, totalCount) {
        const badge = document.getElementById('activeFilterBadge');
        if (badge) {
            let activeCount = 0;
            if (this.state.search) activeCount++;
            if (this.state.status !== 'all') activeCount++;
            activeCount += this.state.categories.size;

            if (activeCount > 0) {
                badge.style.display = 'inline-flex';
                badge.textContent = `${filteredCount} of ${totalCount} items (${activeCount} active filter${activeCount > 1 ? 's' : ''})`;
            } else {
                badge.style.display = 'inline-flex';
                badge.textContent = `Showing all ${totalCount} items`;
            }
        }
    }

    filterItem(item) {
        // Search filter
        if (this.state.search) {
            const title = (item.title || '').toLowerCase();
            const desc = (item.description || '').toLowerCase();
            const addr = (item.address || '').toLowerCase();
            const ward = (item.ward || '').toLowerCase();
            const cat = (item.category || '').toLowerCase();
            const id = (item._id || item.id || '').toString().toLowerCase();

            const query = this.state.search;
            const matches = title.includes(query) || desc.includes(query) ||
                            addr.includes(query) || ward.includes(query) ||
                            cat.includes(query) || id.includes(query);
            if (!matches) return false;
        }

        // Status / Severity filter
        if (this.state.status !== 'all') {
            const st = (item.status || '').toLowerCase();
            const sev = (item.severity || '').toLowerCase();
            const s = this.state.status;

            if (s === 'open' && (st === 'closed' || st === 'officer_verified')) return false;
            else if (s === 'in_progress' && !['assigned', 'work_started', 'work_completed'].includes(st)) return false;
            else if (s === 'closed' && !['closed', 'officer_verified'].includes(st)) return false;
            else if (['critical', 'high', 'medium', 'low'].includes(s) && sev !== s) return false;
        }

        // Category multi-select filter
        if (this.state.categories.size > 0) {
            const itemCat = (item.category || '').toLowerCase();
            if (!this.state.categories.has(itemCat)) return false;
        }

        return true;
    }

    notify() {
        this.onFilterChange(this.state);
    }
}
