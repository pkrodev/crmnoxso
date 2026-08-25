/*
  Inicjalizacja FullCalendara — jedyne miejsce w aplikacji z własnym
  JavaScriptem. Reszta interfejsu jest budowana po stronie serwera i podmieniana
  przez HTMX; tutaj się nie da, bo kalendarz jest komponentem przeglądarki.

  Skrypt robi dokładnie trzy rzeczy:
    1. rysuje siatkę i pobiera wydarzenia z endpointu JSON,
    2. po kliknięciu w wydarzenie prosi serwer o gotowy FRAGMENT HTML i wstawia
       go w panel obok (żądaniem HTMX, nie własnym fetch-em),
    3. przeładowuje wydarzenia, gdy serwer o to poprosi nagłówkiem HX-Trigger.

  Żadnej logiki biznesowej tu nie ma i nie powinno być.
*/
document.addEventListener('DOMContentLoaded', function () {
  var element = document.getElementById('kalendarz');
  if (!element || typeof FullCalendar === 'undefined') {
    return;
  }

  var panelSelector = element.dataset.panel;
  // Adres panelu buduje serwer z podstawionym zerem — podmieniamy je na numer
  // klikniętego wydarzenia, zamiast sklejać ścieżkę w JavaScripcie.
  var eventUrlTemplate = element.dataset.eventUrl;
  var newUrl = element.dataset.newUrl;

  function pokazFragment(url) {
    htmx.ajax('GET', url, { target: panelSelector, swap: 'innerHTML' });
  }

  /* Polskie nazwy przycisków i dni. Tydzień zaczyna się w poniedziałek. */
  var polski = {
    code: 'pl',
    week: { dow: 1, doy: 4 },
    buttonText: {
      prev: 'Poprzedni',
      next: 'Następny',
      today: 'Dziś',
      month: 'Miesiąc',
      week: 'Tydzień',
      day: 'Dzień',
      list: 'Agenda'
    },
    weekText: 'Tydz',
    allDayText: 'Cały dzień',
    moreLinkText: 'więcej',
    noEventsText: 'Brak wydarzeń w tym okresie'
  };

  var calendar = new FullCalendar.Calendar(element, {
    locale: polski,
    initialView: 'dayGridMonth',
    headerToolbar: {
      left: 'prev,next today',
      center: 'title',
      right: 'dayGridMonth,timeGridWeek,listWeek'
    },
    height: 'auto',
    firstDay: 1,
    /* Wydarzenia z godziną domyślnie trwają godzinę — z rozmowy pada
       „o czternastej", nigdy „od czternastej do piętnastej". */
    defaultTimedEventDuration: '01:00',
    /* Bez tego widok miesiąca rysuje kropkę zamiast kafelka, a wtedy nie widać
       kolorów odróżniających propozycję z AI od potwierdzonego terminu. */
    eventDisplay: 'block',
    displayEventEnd: false,
    dayMaxEvents: 4,
    nowIndicator: true,
    /* Godziny w formacie 14:00, a nie 2 PM. */
    eventTimeFormat: { hour: '2-digit', minute: '2-digit', hour12: false },
    slotLabelFormat: { hour: '2-digit', minute: '2-digit', hour12: false },

    events: element.dataset.feed,

    eventClick: function (info) {
      info.jsEvent.preventDefault();
      pokazFragment(eventUrlTemplate.replace(/0$/, info.event.id));
    },

    /* Kliknięcie w pusty dzień otwiera formularz nowego wydarzenia z tą datą. */
    dateClick: function (info) {
      pokazFragment(newUrl + '?day=' + info.dateStr.slice(0, 10));
    }
  });

  calendar.render();

  /* Serwer po zapisie odsyła nagłówek HX-Trigger: kalendarz:odswiez.
     HTMX zamienia go na zdarzenie DOM, a my przeładowujemy wydarzenia, żeby
     potwierdzony termin od razu zmienił wygląd w siatce. */
  document.body.addEventListener('kalendarz:odswiez', function () {
    calendar.refetchEvents();
  });
});
