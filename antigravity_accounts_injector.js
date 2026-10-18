(() => {
    // 1. Bloquear apertura involuntaria de navegador externo
    try {
        if (window.electron && window.electron.openExternal) {
            window.electron.openExternal = () => Promise.resolve();
        }
        window.open = () => null;
    } catch (e) {}

    // 2. Auto-descartar de inmediato modales secundarios (Security Notice, Terms, etc.)
    function autoDismissSecurityNotice() {
        try {
            const acceptBtn = document.querySelector('button[data-testid="accept-terms-btn"]') ||
                Array.from(document.getElementsByTagName('button')).find(b => {
                    const t = b.textContent;
                    return t && (t.includes('Accept and continue') || t.includes('Accept & Continue'));
                });
            if (acceptBtn) {
                acceptBtn.click();
                return true;
            }
        } catch (e) {}
        return false;
    }

    autoDismissSecurityNotice();

    // Observer ultraligero solo para hijos directos del body (modales y portales)
    if (!window.__agModalDismissObserver) {
        try {
            window.__agModalDismissObserver = new MutationObserver((mutations) => {
                for (const m of mutations) {
                    if (m.addedNodes.length > 0) {
                        autoDismissSecurityNotice();
                        break;
                    }
                }
            });
            window.__agModalDismissObserver.observe(document.body, { childList: true, subtree: false });
        } catch (e) {}
    }

    // Busqueda segura, finita y no-bloqueante del store de Redux (maximo 100 nodos con Set visitados)
    function getReduxStore() {
        if (window.__antigravityReduxStore) return window.__antigravityReduxStore;
        try {
            const root = document.querySelector('#root');
            if (!root) return null;
            const fKey = Object.keys(root).find(k => k.startsWith('__reactFiber$') || k.startsWith('__reactContainer$'));
            if (!fKey) return null;

            const queue = [root[fKey]];
            const visited = new Set();
            let steps = 0;
            while (queue.length > 0 && steps < 100) {
                steps++;
                const f = queue.shift();
                if (!f || visited.has(f)) continue;
                visited.add(f);

                if (f.memoizedProps && f.memoizedProps.value && f.memoizedProps.value.store) {
                    window.__antigravityReduxStore = f.memoizedProps.value.store;
                    return window.__antigravityReduxStore;
                }
                if (f.stateNode && f.stateNode.store) {
                    window.__antigravityReduxStore = f.stateNode.store;
                    return window.__antigravityReduxStore;
                }
                if (f.child && !visited.has(f.child)) queue.push(f.child);
                if (f.sibling && !visited.has(f.sibling)) queue.push(f.sibling);
            }
        } catch (e) {}
        return null;
    }

    // Interceptar retrieveUserQuotaSummary para que Models & Usage refleje los tokens de la cuenta activa
    function hookQuotaSummary() {
        try {
            const auth = window.__antigravityCore && window.__antigravityCore.authService;
            if (!auth || !auth._lsClient) return;
            if (auth._lsClient.__quotaHooked) return;
            auth._lsClient.__quotaHooked = true;

            const origQuota = auth._lsClient.retrieveUserQuotaSummary;
            auth._lsClient.retrieveUserQuotaSummary = async function(arg1, arg2) {
                const res = await origQuota.call(this, arg1, arg2);
                try {
                    const activeAcc = (window.__agLastAccounts || []).find(a => a.is_active);
                    if (activeAcc && res && res.response && Array.isArray(res.response.groups)) {
                        const p5h = typeof activeAcc.five_hour_remaining_pct === 'number' ? activeAcc.five_hour_remaining_pct / 100.0 : 1.0;
                        const pwk = typeof activeAcc.weekly_remaining_pct === 'number' ? activeAcc.weekly_remaining_pct / 100.0 : 1.0;

                        for (const g of res.response.groups) {
                            if (g.displayName === 'Gemini Models' && Array.isArray(g.buckets)) {
                                for (const b of g.buckets) {
                                    if (b.bucketId === 'gemini-5h' && b.remaining) {
                                        b.remaining.value = p5h;
                                        b.description = p5h >= 1.0 ? 'Your 5-hour limit is fully refreshed.' : `Five hour remaining: ${Math.round(p5h * 100)}%`;
                                    }
                                    if (b.bucketId === 'gemini-weekly' && b.remaining) {
                                        b.remaining.value = pwk;
                                        b.description = pwk >= 1.0 ? 'Your weekly limit is fully refreshed.' : `Weekly remaining: ${Math.round(pwk * 100)}%`;
                                    }
                                }
                            }
                        }
                    }
                } catch (eHook) {}
                return res;
            };
        } catch (e) {}
    }

    function syncReduxUserStatus(email, name) {
        const store = getReduxStore();
        if (!store) return;
        try {
            const currState = store.getState();
            if (currState && currState.userStatus) {
                const newUserStatus = Object.assign({}, currState.userStatus, {
                    email: email,
                    name: name
                });
                store.dispatch({
                    type: 'userStatus/setUserStatus',
                    payload: newUserStatus
                });
            }
        } catch (e) {}
        hookQuotaSummary();
    }

    function tryInject() {
        const existingBtn = document.getElementById('antigravity-accounts-menu-item');
        const existingDropdown = document.getElementById('antigravity-accounts-dropdown');

        // Si ya existen y estan vivos en el DOM, solo refrescar datos
        if (existingBtn && existingDropdown && document.body.contains(existingDropdown)) {
            hookQuotaSummary();
            if (window.__agRefreshAccounts) {
                window.__agRefreshAccounts();
            }
            return true;
        }

        // Limpiar elementos huerfanos si existieran
        if (existingBtn) existingBtn.remove();
        if (existingDropdown) existingDropdown.remove();

        const menuItems = Array.from(document.querySelectorAll('[data-testid="title-menu-bar-item"]'))
            .filter(b => !b.closest('#antigravity-accounts-menu-item') && !b.innerText.includes('Cuentas'));
        if (!menuItems || menuItems.length === 0) {
            return false;
        }

        const winBtn = menuItems.find(b => b.innerText.trim().startsWith('Window')) || menuItems[menuItems.length - 1];
        const containerParent = winBtn.closest('.relative') ? winBtn.closest('.relative').parentElement : winBtn.parentElement;
        if (!containerParent) return false;

        // Contenedor principal del boton
        const container = document.createElement('div');
        container.id = 'antigravity-accounts-menu-item';
        container.className = 'relative';
        container.style.appRegion = 'no-drag';

        // Boton Cuentas en barra de titulos
        const btn = document.createElement('button');
        btn.id = 'antigravity-accounts-btn';
        btn.className = winBtn.className;
        btn.setAttribute('data-testid', 'title-menu-bar-item');
        btn.style.display = 'inline-flex';
        btn.style.alignItems = 'center';
        btn.style.gap = '6px';
        btn.style.padding = '0 8px';
        btn.style.cursor = 'pointer';
        btn.innerHTML = `<span>Cuentas</span><span id="ag-btn-active-pill" style="font-size:10px;color:#3fb950;background:rgba(63,185,80,0.15);padding:1px 6px;border-radius:6px;font-weight:600;border:1px solid rgba(63,185,80,0.3);">...</span>`;

        // Menu desplegable flotante premium
        const dropdown = document.createElement('div');
        dropdown.id = 'antigravity-accounts-dropdown';
        dropdown.style.display = 'none';
        dropdown.style.position = 'fixed';
        dropdown.style.top = '34px';
        dropdown.style.left = '180px';
        dropdown.style.width = '440px';
        dropdown.style.background = '#18181b';
        dropdown.style.border = '1px solid rgba(255, 255, 255, 0.14)';
        dropdown.style.borderRadius = '10px';
        dropdown.style.boxShadow = '0 20px 60px rgba(0, 0, 0, 0.9)';
        dropdown.style.zIndex = '999999';
        dropdown.style.fontFamily = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
        dropdown.style.color = '#ffffff';
        dropdown.style.padding = '8px 0';
        dropdown.style.userSelect = 'none';

        dropdown.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 16px 6px 16px;border-bottom:1px solid rgba(255,255,255,0.06);">
                <div style="display:flex;align-items:center;gap:6px;">
                    <span style="font-size:13px;font-weight:600;color:#ffffff;">Cuentas Google AI Pro</span>
                    <span style="font-size:10px;color:#a1a1aa;background:rgba(255,255,255,0.06);padding:1px 5px;border-radius:4px;">7 Disponibles</span>
                </div>
                <div id="ag-active-badge-top" style="font-size:11px;color:#3fb950;background:rgba(63,185,80,0.12);padding:2px 8px;border-radius:10px;border:1px solid rgba(63,185,80,0.3);font-weight:600;">
                    Cargando...
                </div>
            </div>

            <!-- Tarjeta fija de 142px con soporte de cuota 5h y semanal -->
            <div style="margin:8px 12px;height:142px;min-height:142px;max-height:142px;background:#101012;border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:12px 14px;box-sizing:border-box;display:flex;flex-direction:column;justify-content:space-between;" id="ag-card-container">
                <div id="ag-gemini-card-content">
                    <div style="color:#888;font-size:12px;text-align:center;padding-top:40px;">Cargando metricas en tiempo real...</div>
                </div>
            </div>

            <div style="font-size:11px;font-weight:600;color:#a1a1aa;text-transform:uppercase;letter-spacing:0.5px;padding:6px 16px;display:flex;justify-content:space-between;align-items:center;">
                <span>Seleccionar Cuenta Activa</span>
                <span style="color:#3fb950;font-size:10px;text-transform:none;">Clic directo para cambiar</span>
            </div>

            <div id="ag-accounts-list" style="max-height:280px;overflow-y:auto;padding:0 4px;"></div>

            <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 14px 4px 14px;border-top:1px solid rgba(255,255,255,0.06);font-size:11px;color:#a1a1aa;margin-top:4px;">
                <span id="ag-status-feedback" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:260px;color:#a1a1aa;">Listo para cambiar cuenta</span>
                <div style="display:flex;gap:6px;">
                    <button id="ag-refresh-btn" style="background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.12);color:#ddd;padding:3px 8px;border-radius:4px;cursor:pointer;font-size:10.5px;">Refrescar</button>
                    <button id="ag-close-btn" style="background:transparent;border:1px solid rgba(255,255,255,0.1);color:#aaa;padding:3px 8px;border-radius:4px;cursor:pointer;font-size:10.5px;">Cerrar</button>
                </div>
            </div>
        `;

        container.appendChild(btn);
        document.body.appendChild(dropdown);
        containerParent.appendChild(container);
        window.__antigravityAccountsInjected = true;

        let cachedAccounts = [];
        let activeOverrideId = null;

        function updateCard(acc) {
            const cardContent = document.getElementById('ag-gemini-card-content');
            if (!cardContent || !acc) return;

            const r = 9;
            const circ = 2 * Math.PI * r;
            const rem5h = typeof acc.five_hour_remaining_pct === 'number' ? acc.five_hour_remaining_pct : 100;
            const offset5h = Math.max(0, circ * (1 - rem5h / 100));
            const remWk = typeof acc.weekly_remaining_pct === 'number' ? acc.weekly_remaining_pct : 100;
            const offsetWk = Math.max(0, circ * (1 - remWk / 100));

            const color5h = rem5h <= 15 ? '#f85149' : (rem5h <= 50 ? '#d29922' : '#3fb950');
            const colorWk = remWk <= 15 ? '#f85149' : (remWk <= 50 ? '#d29922' : '#3fb950');

            const activeTag = acc.is_active ? '<span style="color:#3fb950;font-size:10px;background:rgba(63,185,80,0.12);padding:1px 5px;border-radius:4px;border:1px solid rgba(63,185,80,0.3);font-weight:600;">ACTIVA</span>' : '<span style="color:#888;font-size:10px;">Inactiva</span>';

            cardContent.innerHTML = `
                <div>
                    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:3px;">
                        <div style="display:flex;align-items:center;gap:6px;">
                            <span style="font-size:13px;font-weight:600;color:#ffffff;">${acc.name}</span>
                            ${activeTag}
                        </div>
                        <span style="font-size:10.5px;color:#71717a;">Google AI Pro</span>
                    </div>

                    <!-- 5-Hour Limit Row -->
                    <div style="display:flex;align-items:center;justify-content:space-between;font-size:11.5px;margin-top:2px;">
                        <div>
                            <span style="font-weight:500;color:#ddd;">Five Hour Limit</span>
                            <span style="font-size:10px;color:#8b949e;margin-left:6px;">(${rem5h >= 100 ? '100% disponible' : 'Recarga: ' + (acc.five_hour_refresh_text || '3h')})</span>
                        </div>
                        <div style="display:flex;align-items:center;gap:6px;">
                            <span style="font-size:11.5px;font-weight:600;color:${color5h};">${rem5h}%</span>
                            <svg width="18" height="18" viewBox="0 0 24 24" style="transform:rotate(-90deg);">
                                <circle cx="12" cy="12" r="${r}" fill="none" stroke="rgba(255,255,255,0.1)" stroke-width="2.5" />
                                <circle cx="12" cy="12" r="${r}" fill="none" stroke="${color5h}" stroke-width="2.5" stroke-dasharray="${circ} ${circ}" stroke-dashoffset="${offset5h}" stroke-linecap="round" />
                            </svg>
                        </div>
                    </div>

                    <!-- Weekly Limit Row -->
                    <div style="display:flex;align-items:center;justify-content:space-between;font-size:11.5px;margin-top:2px;">
                        <div>
                            <span style="font-weight:500;color:#ddd;">Weekly Limit</span>
                            <span style="font-size:10px;color:#8b949e;margin-left:6px;">(${remWk >= 100 ? '100% disponible' : 'Resetea: ' + (acc.weekly_refresh_text || '6d')})</span>
                        </div>
                        <div style="display:flex;align-items:center;gap:6px;">
                            <span style="font-size:11.5px;font-weight:600;color:${colorWk};">${remWk}%</span>
                            <svg width="18" height="18" viewBox="0 0 24 24" style="transform:rotate(-90deg);">
                                <circle cx="12" cy="12" r="${r}" fill="none" stroke="rgba(255,255,255,0.1)" stroke-width="2.5" />
                                <circle cx="12" cy="12" r="${r}" fill="none" stroke="${colorWk}" stroke-width="2.5" stroke-dasharray="${circ} ${circ}" stroke-dashoffset="${offsetWk}" stroke-linecap="round" />
                            </svg>
                        </div>
                    </div>
                </div>

                <div style="display:flex;align-items:center;justify-content:space-between;border-top:1px solid rgba(255,255,255,0.06);padding-top:4px;margin-top:3px;">
                    <span style="font-size:11px;color:#a1a1aa;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:250px;">${acc.email || acc.name}</span>
                    <div style="display:flex;gap:3px;">
                        <span style="font-size:9px;background:rgba(255,255,255,0.06);color:#888;padding:1px 4px;border-radius:3px;">flash</span>
                        <span style="font-size:9px;background:rgba(255,255,255,0.06);color:#888;padding:1px 4px;border-radius:3px;">pro</span>
                    </div>
                </div>
            `;
        }

        function renderMenu(data) {
            cachedAccounts = data.accounts || [];
            window.__agLastAccounts = cachedAccounts;
            if (activeOverrideId) {
                cachedAccounts.forEach(a => {
                    a.is_active = (a.id === activeOverrideId);
                });
            }
            const activeAcc = cachedAccounts.find(a => a.is_active) || cachedAccounts[0];

            const activeBadge = document.getElementById('ag-active-badge-top');
            if (activeBadge && activeAcc) {
                activeBadge.textContent = activeAcc.name + ' [ACTIVA]';
            }

            const pill = document.getElementById('ag-btn-active-pill');
            if (pill && activeAcc) {
                pill.textContent = activeAcc.name;
            }

            if (activeAcc) {
                updateCard(activeAcc);
            }

            const listEl = document.getElementById('ag-accounts-list');
            if (!listEl) return;
            listEl.innerHTML = '';

            cachedAccounts.forEach(acc => {
                const item = document.createElement('div');
                item.id = `ag-acc-row-${acc.id}`;
                item.style.display = 'flex';
                item.style.alignItems = 'center';
                item.style.justifyContent = 'space-between';
                item.style.padding = '8px 12px';
                item.style.margin = '2px 0';
                item.style.borderRadius = '6px';
                item.style.cursor = 'pointer';
                item.style.transition = 'background 0.12s ease';

                function applyVisual(isActive) {
                    item.style.background = isActive ? 'rgba(63,185,80,0.10)' : 'transparent';
                    item.style.borderLeft = isActive ? '3px solid #3fb950' : '3px solid transparent';
                }
                applyVisual(acc.is_active);

                item.onmouseenter = () => {
                    if (!acc.is_active) item.style.background = 'rgba(255,255,255,0.05)';
                    updateCard(acc);
                };
                item.onmouseleave = () => {
                    applyVisual(acc.is_active);
                    const currentActive = cachedAccounts.find(a => a.is_active) || acc;
                    updateCard(currentActive);
                };

                // Click instantaneo: actualiza UI, despacha fetch y auto-cierra el menu suavemente
                item.onclick = async () => {
                    activeOverrideId = acc.id;
                    cachedAccounts.forEach(other => {
                        other.is_active = (other.id === acc.id);
                        const row = document.getElementById(`ag-acc-row-${other.id}`);
                        if (row) {
                            row.style.background = other.is_active ? 'rgba(63,185,80,0.10)' : 'transparent';
                            row.style.borderLeft = other.is_active ? '3px solid #3fb950' : '3px solid transparent';
                            const badge = row.querySelector('.ag-act-badge');
                            if (badge) badge.style.display = other.is_active ? 'inline' : 'none';
                            const checkmark = row.querySelector('.ag-act-check');
                            if (checkmark) {
                                checkmark.textContent = other.is_active ? '[✓]' : '•';
                                checkmark.style.color = other.is_active ? '#3fb950' : '#888';
                            }
                        }
                    });

                    const topBadge = document.getElementById('ag-active-badge-top');
                    if (topBadge) topBadge.textContent = acc.name + ' [ACTIVA]';

                    const topPill = document.getElementById('ag-btn-active-pill');
                    if (topPill) topPill.textContent = acc.name;

                    updateCard(acc);

                    const feedback = document.getElementById('ag-status-feedback');
                    if (feedback) {
                        feedback.style.color = '#ddd';
                        feedback.textContent = `Cambiando a ${acc.name}...`;
                    }

                    // Auto-cerrar el menu automaticamente tras mostrar la seleccion
                    setTimeout(() => {
                        dropdown.style.display = 'none';
                    }, 400);

                    try {
                        const switchRes = await fetch(`http://127.0.0.1:59123/api/switch?account=${encodeURIComponent(acc.id)}`);
                        const result = await switchRes.json();
                        if (result.ok) {
                            if (feedback) {
                                feedback.style.color = '#3fb950';
                                feedback.textContent = `[OK] Cuenta activa: ${acc.name} (${acc.email})`;
                            }
                            syncReduxUserStatus(acc.email, acc.name);
                            try {
                                if (window.__antigravityCore && window.__antigravityCore.authService) {
                                    window.__antigravityCore.authService.checkCurrentAuthStatus();
                                    window.__antigravityCore.authService.refreshUserStatus();
                                }
                            } catch (eAuth) {}
                            autoDismissSecurityNotice();
                            setTimeout(() => {
                                try {
                                    if (window.__antigravityCore && window.__antigravityCore.authService) {
                                        window.__antigravityCore.authService.checkCurrentAuthStatus();
                                        window.__antigravityCore.authService.refreshUserStatus();
                                    }
                                } catch (e) {}
                                refreshAccounts();
                                autoDismissSecurityNotice();
                            }, 2500);
                        } else {
                            if (feedback) {
                                feedback.style.color = '#f85149';
                                feedback.textContent = `[AVISO] ${result.message || 'Error al cambiar'}`;
                            }
                        }
                    } catch (e) {
                        if (feedback) {
                            feedback.style.color = '#f85149';
                            feedback.textContent = `[ERROR] Fallo al cambiar cuenta: ${e.message}`;
                        }
                    }
                };

                let warningBadge = '';
                if (acc.show_weekly_warning) {
                    warningBadge = `<span style="font-size:10px;color:#f85149;background:rgba(248,81,73,0.15);padding:1px 5px;border-radius:4px;border:1px solid rgba(248,81,73,0.3);margin-left:4px;">! Sem: ${acc.weekly_remaining_pct}%</span>`;
                }

                const activeBadgeHtml = `<span class="ag-act-badge" style="display:${acc.is_active ? 'inline' : 'none'};font-size:10px;color:#3fb950;background:rgba(63,185,80,0.14);padding:1px 5px;border-radius:4px;border:1px solid rgba(63,185,80,0.3);margin-left:4px;font-weight:600;">[ACTIVA]</span>`;

                item.innerHTML = `
                    <div style="display:flex;align-items:center;gap:8px;min-width:0;">
                        <span class="ag-act-check" style="font-size:12px;color:${acc.is_active ? '#3fb950' : '#888'};font-weight:bold;width:14px;text-align:center;">${acc.is_active ? '[✓]' : '•'}</span>
                        <div style="display:flex;flex-direction:column;min-width:0;">
                            <div style="display:flex;align-items:center;">
                                <span style="font-size:12.5px;font-weight:${acc.is_active ? '600' : '500'};color:${acc.is_active ? '#ffffff' : '#e4e4e7'};">${acc.name}</span>
                                ${activeBadgeHtml}
                                ${warningBadge}
                            </div>
                            <span style="font-size:11px;color:#71717a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${acc.email}</span>
                        </div>
                    </div>
                    <div style="display:flex;align-items:center;gap:6px;flex-shrink:0;">
                        <span style="font-size:11px;color:${(typeof acc.five_hour_remaining_pct === 'number' ? acc.five_hour_remaining_pct : 100) < 10 ? '#f85149' : '#a1a1aa'};font-family:monospace;font-weight:500;">5h: ${typeof acc.five_hour_remaining_pct === 'number' ? acc.five_hour_remaining_pct : 100}%</span>
                        <span style="font-size:10.5px;color:#555;">•</span>
                        <span style="font-size:11px;color:${(typeof acc.weekly_remaining_pct === 'number' ? acc.weekly_remaining_pct : 100) <= 50 ? ((typeof acc.weekly_remaining_pct === 'number' ? acc.weekly_remaining_pct : 100) <= 15 ? '#f85149' : '#d29922') : '#3fb950'};font-family:monospace;font-weight:500;">Sem: ${typeof acc.weekly_remaining_pct === 'number' ? acc.weekly_remaining_pct : 100}%</span>
                    </div>
                `;
                listEl.appendChild(item);
            });
        }

        async function refreshAccounts(force = false) {
            try {
                const url = force ? 'http://127.0.0.1:59123/api/tokens?refresh=1' : 'http://127.0.0.1:59123/api/tokens';
                const res = await fetch(url);
                if (!res.ok) return;
                const data = await res.json();
                renderMenu(data);
            } catch (e) {}
        }

        window.__agRefreshAccounts = refreshAccounts;

        btn.onclick = (e) => {
            e.stopPropagation();
            const isOpen = dropdown.style.display === 'block';
            dropdown.style.display = isOpen ? 'none' : 'block';
            if (!isOpen) {
                const rect = btn.getBoundingClientRect();
                dropdown.style.top = (rect.bottom + 4) + 'px';
                dropdown.style.left = Math.max(10, rect.left) + 'px';
                refreshAccounts(false);
            }
        };

        const closeBtn = document.getElementById('ag-close-btn');
        if (closeBtn) {
            closeBtn.onclick = () => { dropdown.style.display = 'none'; };
        }

        const refreshBtn = document.getElementById('ag-refresh-btn');
        if (refreshBtn) {
            refreshBtn.onclick = async (e) => {
                e.stopPropagation();
                activeOverrideId = null;
                const fb = document.getElementById('ag-status-feedback');
                if (fb) fb.textContent = 'Consultando cuotas en vivo...';
                await refreshAccounts(true);
                if (fb) fb.textContent = 'Cuotas actualizadas';
            };
        }

        if (!window.__agDocClickListenerAttached) {
            window.__agDocClickListenerAttached = true;
            document.addEventListener('click', (e) => {
                const curDropdown = document.getElementById('antigravity-accounts-dropdown');
                const curBtn = document.getElementById('antigravity-accounts-btn');
                if (curDropdown && curDropdown.style.display === 'block') {
                    if (!curDropdown.contains(e.target) && (!curBtn || !curBtn.contains(e.target))) {
                        curDropdown.style.display = 'none';
                    }
                }
            });
        }

        hookQuotaSummary();
        refreshAccounts();
        return true;
    }

    if (tryInject()) {
        return { status: "injected_successfully" };
    } else {
        return { error: "menu_bar_not_ready" };
    }
})();
