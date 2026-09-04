"""``/add``, ``/list``, ``/remove``, ``/change``, ``/change_all``.

The multi-step flows behind these commands: address prompt, DexScreener lookup,
confirmation, threshold prompt. Address validation and chain detection go through
``chains.registry``; the subscription limit is enforced on creation and, as in the legacy
bot, counts alerts of every source rather than only ``dex``.
"""
