#!/bin/bash

if pgrep -f -- "--port 8001" > /dev/null; then
    exit 0
fi

cd /home2/mashimarketing/fastapi_app_real_state

nohup /home2/mashimarketing/virtualenv/fastapi_app_real_state/3.11/bin/python \
-m uvicorn app.main:app --host 0.0.0.0 --port 8001 \
>> cron_uvicorn.log 2>&1 &
