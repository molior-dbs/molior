Logging
=======

All molior services log to syslog per default.
If you only want to see the log of a specific module / service you can do:

.. code:: sh

    sudo journalctl -u molior-server


Log levels and log formatters can be specified in the ``/etc/molior/logging.yml``
config file.

.. code::

    formatters:
        syslog:
            format: '[%(levelname)s] %(name)s: %(message)s'
            datefmt: '%H:%M:%S'

    handlers:
        syslog:
            level: DEBUG
            class: logging.handlers.SysLogHandler
            formatter: syslog
            address: /dev/log

    loggers:
        '':
            handlers: [syslog]
            level: INFO
            propagate: false

        molior:
            level: DEBUG
            propagate: true
