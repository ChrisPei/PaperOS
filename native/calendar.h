#ifndef PAPEROS_CALENDAR_H
#define PAPEROS_CALENDAR_H
#include <stdbool.h>
#include <stddef.h>
int paperos_month_days(int year,int month);
int paperos_weekday(int year,int month,int day);
bool paperos_lunar(int year,int month,int day,int *ly,int *lm,int *ld,bool *leap);
void paperos_lunar_label(int year,int month,int day,bool full,char *text,size_t size);
const char *paperos_solar_term(int year,int month,int day);
const char *paperos_next_solar_term(int year,int month,int day,int *ny,int *nm,int *nd,int *days_until);
void paperos_festival_label(int year,int month,int day,char *text,size_t size);
void paperos_calendar_events(int year,int month,int day,char *text,size_t size);
#endif
