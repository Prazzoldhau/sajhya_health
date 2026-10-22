import csv
import urllib.parse

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from .access import workspace_context, workspace_profile
from .reports import build_report, resolve_period, to_csv_rows


@login_required
def reports(request):
    profile = workspace_profile(request)
    if profile is None:
        return redirect('accounts:welcome')
    kind, start, end, label, prev, nxt = resolve_period(request.GET)
    report = build_report(profile, start, end)
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="sajhya-report-{start}-to-{end}.csv"'
        response.write('﻿')  # so Excel reads UTF-8
        csv.writer(response).writerows(to_csv_rows(label, report))
        return response
    link = lambda params: '?' + urllib.parse.urlencode(params) if params else ''
    today = timezone.localdate()
    context = workspace_context(request.user, profile)
    context.update({
        'active': 'reports', 'kind': kind, 'start': start, 'end': end, 'label': label, 'report': report,
        'prev_link': link(prev), 'next_link': link(nxt), 'this_week': '?period=week', 'this_month': '?period=month',
        'csv_link': '?' + urllib.parse.urlencode({**request.GET.dict(), 'period': kind, 'start': start, 'end': end, 'export': 'csv'}) if kind == 'custom'
                    else '?' + urllib.parse.urlencode({**request.GET.dict(), 'period': kind, 'export': 'csv'}),
        'today': today,
    })
    return render(request, 'accounts/reports.html', context)
