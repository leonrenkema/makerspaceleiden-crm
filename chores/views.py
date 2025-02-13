import time
from collections import defaultdict
from datetime import datetime
from django.shortcuts import render
from selfservice.aggregator_adapter import get_aggregator_adapter
from django.http import HttpResponse
from django.shortcuts import redirect
from django.core.exceptions import ObjectDoesNotExist
from .admin import ChoreAdmin
from .models import ChoreVolunteer, Chore
from django.contrib.auth.decorators import login_required

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string, get_template

import logging

logger = logging.getLogger(__name__)


@login_required
def index(request):
    current_user_id = request.user.id

    aggregator_adapter = get_aggregator_adapter()
    if not aggregator_adapter:
        return HttpResponse(
            "No aggregator configuration found", status=500, content_type="text/plain"
        )

    now = time.time()
    volunteers_turns = ChoreVolunteer.objects.filter(timestamp__gte=now)
    volunteers_by_key = defaultdict(list)
    for turn in volunteers_turns:
        key = f"{turn.chore.id}-{turn.timestamp}"
        volunteers_by_key[key].append(turn.user)

    data = aggregator_adapter.get_chores()

    event_groups = []
    ts = None
    if data != None:
        for event in data["events"]:
            event_ts = datetime.fromtimestamp(event["when"]["timestamp"])
            event_ts_str = event_ts.strftime("%d%m%Y")
            event["time_str"] = event_ts.strftime("%H:%M")
            chore_id = event["chore"]["chore_id"]
            timestamp = event["when"]["timestamp"]
            event["volunteers"] = volunteers_by_key[f"{chore_id}-{timestamp}"]
            num_missing_volunteers = event["chore"]["min_required_people"] - len(
                event["volunteers"]
            )
            this_user_volunteered = current_user_id in [
                user.id for user in event["volunteers"]
            ]
            if num_missing_volunteers > 0:
                for idx in range(num_missing_volunteers):
                    if idx == 0 and not this_user_volunteered:
                        event["volunteers"].append("offer_volunteering")
                    else:
                        event["volunteers"].append(None)
            if event_ts_str != ts:
                ts = event_ts_str
                event_groups.append(
                    {"ts_str": event_ts.strftime("%A %d/%m/%Y"), "events": []}
                )
            event_groups[-1]["events"].append(event)

    context = {
        "title": "Chores",
        "event_groups": event_groups,
    }

    return render(request, "chores.html", context)


@login_required
def signup(request, chore_id, ts):
    try:
        chore = Chore.objects.get(pk=chore_id)
    except ObjectDoesNotExist as e:
        return HttpResponse("Chore not found", status=404, content_type="text/plain")

    try:
        ChoreVolunteer.objects.create(user=request.user, chore=chore, timestamp=ts)
    except Exception as e:
        logger.error("Something else went wrong during create: {0}".format(e))
        raise e
    try:
        context = {"chore": chore, "volunteer": request.user}
        subject = render_to_string("notify_email.subject.txt", context).strip()
        body = render_to_string("notify_email.txt", context)

        EmailMessage(
            subject,
            body,
            to=[request.user.email, settings.MAILINGLIST],
            from_email=settings.DEFAULT_FROM_EMAIL,
        ).send()
    except Exception as e:
        logger.error("Something else went wrong during mail sent: {0}".format(e))

    return redirect("chores")


@login_required
def remove_signup(request, chore_id, ts):
    try:
        chore = Chore.objects.get(pk=chore_id)
    except ObjectDoesNotExist as e:
        return HttpResponse("Chore not found", status=404, content_type="text/plain")

    try:
        ChoreVolunteer.objects.filter(
            user=request.user, chore=chore, timestamp=ts
        ).delete()
    except Exception as e:
        logger.error("Something else went wrong during delete: {0}".format(e))
        raise e
    try:
        context = {"chore": chore, "volunteer": request.user}
        subject = render_to_string("notify_email_nope.subject.txt", context).strip()
        body = render_to_string("notify_email_nope.txt", context)

        EmailMessage(
            subject,
            body,
            to=[request.user.email, settings.MAILINGLIST],
            from_email=settings.DEFAULT_FROM_EMAIL,
        ).send()
    except Exception as e:
        logger.error("Something else went wrong during remove mail sent: {0}".format(e))

    return redirect("chores")
