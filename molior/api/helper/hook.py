def get_hook_triggers(hook):
    triggers = []
    if hook.notify_src:
        triggers.append("src")
    if hook.notify_deb:
        triggers.append("deb")
    if hook.notify_overall:
        triggers.append("overall")
    return triggers
