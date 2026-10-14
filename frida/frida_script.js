// ============================================================
//  SHADOW CLONER — Frida Script v8.1
//  Bridge: Android broadcast (cross-process safe)
//  Fix: No recursion in hooks
// ============================================================

console.log("==============================================");
console.log("SHADOW FRIDA SCRIPT v8.1 LOADED");
console.log("==============================================");

var HOST_PACKAGE = "com.shadowcloner";
var BROADCAST_ACTION = "com.shadowcloner.FRIDA_EVENT";

var _ctx = null;
function getContext() {
    if (_ctx !== null) return _ctx;
    try {
        var AT = Java.use("android.app.ActivityThread");
        var app = AT.currentApplication();
        if (app !== null) {
            _ctx = app.getApplicationContext();
        }
    } catch(e) {
        console.log("[SHADOW] ctx error: " + e);
    }
    return _ctx;
}

function emit(obj) {
    try {
        var json = JSON.stringify(obj);
        console.log("SHADOW_JSON:" + json);
        try { send(json); } catch(e) {}
        try {
            var ctx = getContext();
            if (ctx !== null) {
                var Intent = Java.use("android.content.Intent");
                var intent = Intent.$new(BROADCAST_ACTION);
                intent.putExtra("json", json);
                intent.setPackage(HOST_PACKAGE);
                ctx.sendBroadcast(intent);
            }
        } catch(e) {
            console.log("[SHADOW] broadcast error: " + e);
        }
    } catch(e) {
        console.log("[SHADOW] emit error: " + e);
    }
}

// ═══ IMMEDIATE BOOT SIGNAL ═══
Java.perform(function() {
    try {
        emit({ type: "script_boot_immediate", version: "8.1", ts: Date.now() });
        var ctx = getContext();
        if (ctx !== null) {
            console.log("[SHADOW] boot: ctx OK, pkg=" + ctx.getPackageName());
        } else {
            console.log("[SHADOW] boot: context null");
        }
    } catch(e) {
        console.log("[SHADOW] boot error: " + e);
    }
});

var hooksInstalled = false;
var installAttempts = 0;
var MAX_INSTALL_ATTEMPTS = 120;

function installHooks() {
    if (hooksInstalled) return;

    installAttempts++;
    if (installAttempts > MAX_INSTALL_ATTEMPTS) {
        emit({ type: "install_timeout", attempts: installAttempts });
        return;
    }

    Java.perform(function() {
        var installedAnything = false;

        // ═══ HOOK 1: BalanceModel.getMoney ═══
        try {
            var BalanceModel = Java.use("org.xplatform.balance.model.BalanceModel");
            var origGetMoney = BalanceModel.getMoney;  // ← SAVE ORIGINAL

            BalanceModel.getMoney.implementation = function() {
                var amount = origGetMoney.call(this);  // ← CALL ORIGINAL
                try {
                    emit({
                        type: "balance_update",
                        balance: Number(amount),
                        source: "BalanceModel.getMoney",
                        ts: Date.now()
                    });
                } catch(e) {}
                return amount;
            };

            installedAnything = true;
            console.log("[SHADOW] BalanceModel.getMoney hooked");
            emit({ type: "balance_hook_ok", ts: Date.now() });
        } catch(e) {
            console.log("[SHADOW] BalanceModel hook failed: " + e);
            emit({ type: "balance_hook_fail", error: String(e) });
        }

        // ═══ HOOK 2: BalanceUseCase ═══
        try {
            var BalanceUseCase = Java.use("org.xplatform.core.domain.usecases.balance.b");
            var origA = BalanceUseCase.a;

            BalanceUseCase.a.overloads.forEach(function(overload) {
                if (overload.holder === undefined) return;  // skip invalid
                var orig = overload;
                overload.implementation = function() {
                    var model = orig.apply(this, arguments);
                    try {
                        if (model !== null && model !== undefined) {
                            var amount = model.getMoney();
                            emit({
                                type: "balance_update",
                                balance: Number(amount),
                                source: "BalanceUseCase",
                                ts: Date.now()
                            });
                        }
                    } catch(e) {}
                    return model;
                };
            });

            installedAnything = true;
            console.log("[SHADOW] BalanceUseCase hooked");
            emit({ type: "balance_usecase_hook_ok", ts: Date.now() });
        } catch(e) {
            console.log("[SHADOW] BalanceUseCase hook failed: " + e);
        }

        // ═══ HOOK 3: Mapper (m70.a) ═══
        try {
            var Mapper = Java.use("m70.a");
            var origMap = Mapper.a;

            Mapper.a.implementation = function(dto) {
                var bean = origMap.call(this, dto);

                try {
                    if (bean === null || bean === undefined) return bean;

                    var status = "";
                    var grid = [];
                    var multipliers = [];
                    var winCols = [];

                    try {
                        var e = bean.e.value;
                        if (e !== null && e !== undefined) {
                            status = e.name ? e.name() : String(e);
                        }
                    } catch(x) {}

                    try {
                        var k = bean.k.value;
                        if (k !== null && k !== undefined) {
                            for (var r = 0; r < k.size(); r++) {
                                var row = k.get(r);
                                var rowArr = [];
                                for (var c = 0; c < row.size(); c++) {
                                    var cell = row.get(c);
                                    var cellName = (cell !== null && cell.name) ? cell.name() : String(cell);
                                    rowArr.push(cellName);
                                }
                                grid.push(rowArr);
                            }
                        }
                    } catch(x) {}

                    try {
                        var g = bean.g.value;
                        if (g !== null && g !== undefined) {
                            for (var i = 0; i < g.size(); i++) {
                                var v = g.get(i);
                                multipliers.push(v.doubleValue ? v.doubleValue() : Number(v));
                            }
                        }
                    } catch(x) {}

                    try {
                        var iL = bean.i.value;
                        if (iL !== null && iL !== undefined) {
                            for (var j = 0; j < iL.size(); j++) {
                                var v2 = iL.get(j);
                                winCols.push(v2.intValue ? v2.intValue() : Number(v2));
                            }
                        }
                    } catch(x) {}

                    emit({
                        type: "grid_update",
                        status: status,
                        grid: grid,
                        multipliers: multipliers,
                        winning_columns: winCols,
                        ts: Date.now()
                    });
                } catch(e) {
                    emit({ type: "mapper_extract_error", error: String(e) });
                }

                return bean;
            };

            installedAnything = true;
            console.log("[SHADOW] Mapper hooked");
            emit({ type: "mapper_hook_ok", ts: Date.now() });
        } catch(e) {
            console.log("[SHADOW] Mapper hook failed: " + e);
        }

        // ═══ HOOK 4: ViewModel ═══
        try {
            var VM = Java.use("org.xplatform.apple_fortune.presentation.game.e");
            var origS0 = VM.s0;

            VM.s0.implementation = function(bean, cont) {
                try {
                    if (bean !== null && bean !== undefined) {
                        emit({
                            type: "vm_bean_received",
                            beanClass: bean.getClass().getName(),
                            ts: Date.now()
                        });
                    }
                } catch(e) {}
                return origS0.call(this, bean, cont);
            };

            installedAnything = true;
            console.log("[SHADOW] ViewModel hooked");
            emit({ type: "vm_hook_ok", ts: Date.now() });
        } catch(e) {
            console.log("[SHADOW] ViewModel hook failed: " + e);
        }

        if (installedAnything) {
            hooksInstalled = true;
            console.log("[SHADOW] Hooks ready");
            emit({ type: "hook_ready", ts: Date.now() });
        } else {
            console.log("[SHADOW] Nothing installed, retry (attempt " + installAttempts + ")");
            setTimeout(installHooks, 500);
        }
    });
}

setTimeout(installHooks, 1000);

setInterval(function() {
    emit({ type: "heartbeat", installed: hooksInstalled, attempts: installAttempts, ts: Date.now() });
}, 30000);
